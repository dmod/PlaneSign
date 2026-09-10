import fcntl
import json
import logging
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import dbus
import dbus.mainloop.glib
from gatt import Advertisement, Application, Characteristic, Service, configure_logging, find_adapter_wait, register_ad_cb, register_app_cb, register_app_error_cb, run_command, run_on_main_loop, set_adapter_name, set_mainloop
from gi.repository import GLib
from wifi import configure_wifi, get_current_wifi_status, scan_wifi

LOG = logging.getLogger("planesign.ble")

BLUEZ_SERVICE_NAME = "org.bluez"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
DEVICE_IFACE = "org.bluez.Device1"
ADAPTER_IFACE = "org.bluez.Adapter1"
PLANESIGN_MASTER_UUID = "3d951a35-76c5-4207-a150-2d0cf7d2bfdd"
DOCKER_CONTAINER_NAME = "PlaneSignRuntime"
DOCKER_IMAGE = "ghcr.io/dmod/planesign:latest"
DOCKER_IMAGE_REPO = "dmod/planesign"
mainloop = None

# Every slow probe runs here. BlueZ dispatches GATT calls on the single GLib main loop
# thread and a connection only has one ATT transaction in flight, so a handler that blocks
# delays every characteristic queued behind it.
WORKERS = ThreadPoolExecutor(max_workers=6, thread_name_prefix="ble-worker")


def summarize(value, limit=120):
    """Single-line, length-capped rendering of a characteristic value for logs."""
    text = " / ".join(str(value).splitlines())
    return text if len(text) <= limit else f"{text[:limit]}… ({len(text)} chars)"


def submit_worker(label, func, *args):
    """Run func on the worker pool.

    ThreadPoolExecutor parks an escaped exception in a Future nobody reads, so without this
    guard a crashing worker would disappear without a single log line.
    """

    def guarded():
        try:
            func(*args)
        except Exception:
            LOG.exception("%s worker crashed", label)

    WORKERS.submit(guarded)


def run_in_background(label, func, on_done=None):
    """Run func on a worker thread; deliver its result back on the main loop thread."""

    def worker():
        started = time.monotonic()
        try:
            result = func()
        except Exception as exc:
            LOG.exception("%s raised", label)
            result = f"error: {exc}"
        LOG.info("%s finished in %.0f ms: %s", label, (time.monotonic() - started) * 1000, summarize(result))
        if on_done is not None:
            run_on_main_loop(on_done, result)

    submit_worker(label, worker)


class CachedValueCharacteristic(Characteristic):
    """Read-only characteristic served from a cache that worker threads keep warm.

    Reads answer from the cache immediately so BlueZ's main loop is never blocked, and the
    refreshed value is pushed to subscribers. The very first read is held open until the
    initial computation lands, so a client never receives the empty placeholder the old
    implementation returned before its background work had finished.
    """

    # 0 disables the periodic refresh; the value is then only recomputed on demand.
    REFRESH_INTERVAL_SECONDS = 0
    # A read older than this triggers a background refresh after the cached value is sent.
    CACHE_TTL_SECONDS = 15.0
    # How long the first read may wait for a value before falling back to PENDING_VALUE.
    # Must stay clear of the client's own read timeout (15 s in flutter_blue_plus), so a
    # slow source degrades to a placeholder plus a notification rather than an app error.
    FIRST_READ_WAIT_SECONDS = 10
    # Empty reads render as "Unknown" in the mobile app, which beats an invented status.
    PENDING_VALUE = ""
    # Warm this value when a client connects.
    REFRESH_ON_CONNECT = True

    def __init__(self, bus, index, uuid, service, extra_flags=()):
        Characteristic.__init__(self, bus, index, uuid, ["read", "notify", *extra_flags], service)
        self._value = None
        self._value_time = 0.0
        self._refreshing = False
        self._pending_reads = []
        self._first_read_timer = None
        self.request_refresh("startup")
        if self.REFRESH_INTERVAL_SECONDS:
            GLib.timeout_add_seconds(self.REFRESH_INTERVAL_SECONDS, self._on_refresh_timer)

    def compute_value(self):
        """Produce the value. Always called on a worker thread, so it may block."""
        raise NotImplementedError

    def start_read(self, options, respond, fail):
        if self._value is None:
            LOG.info("%s: read arrived before the first value was cached; holding the reply", self.name)
            self._pending_reads.append(respond)
            self._arm_first_read_timer()
            self.request_refresh("first read")
            return

        age = time.monotonic() - self._value_time
        respond(self._value)
        if age >= self.CACHE_TTL_SECONDS:
            self.request_refresh(f"cached value was {age:.0f}s old")

    def on_start_notify(self):
        # Gated on REFRESH_ON_CONNECT: the app subscribes to every notifying characteristic
        # the moment it attaches, and some sources are too expensive to run then.
        if self.REFRESH_ON_CONNECT:
            self.refresh_if_stale("client subscribed")

    def refresh_if_stale(self, reason):
        if self._value is None or time.monotonic() - self._value_time >= self.CACHE_TTL_SECONDS:
            self.request_refresh(reason)

    def request_refresh(self, reason):
        if self._refreshing:
            LOG.debug("%s: refresh already in flight, skipping (%s)", self.name, reason)
            return
        self._refreshing = True
        LOG.debug("%s: refreshing (%s)", self.name, reason)
        submit_worker(f"{self.name} refresh", self._refresh_worker)

    def _on_refresh_timer(self):
        self.request_refresh("periodic refresh")
        return True

    def _refresh_worker(self):
        started = time.monotonic()
        try:
            value = self.compute_value()
        except Exception as exc:
            LOG.exception("%s: compute_value raised", self.name)
            value = f"error: {exc}"
        run_on_main_loop(self._publish_value, value, (time.monotonic() - started) * 1000)

    def _publish_value(self, value, elapsed_ms):
        self._refreshing = False
        changed = value != self._value
        self._value = value
        self._value_time = time.monotonic()

        if elapsed_ms >= 1000:
            LOG.warning("%s: refresh took %.0f ms", self.name, elapsed_ms)
        if changed:
            LOG.info("%s = %s (computed in %.0f ms)", self.name, summarize(value), elapsed_ms)

        self._cancel_first_read_timer()
        self._release_pending_reads(value)
        if changed:
            self.notify_value(value)

    def _arm_first_read_timer(self):
        if self._first_read_timer is None:
            self._first_read_timer = GLib.timeout_add_seconds(self.FIRST_READ_WAIT_SECONDS, self._on_first_read_timeout)

    def _cancel_first_read_timer(self):
        if self._first_read_timer is not None:
            GLib.source_remove(self._first_read_timer)
            self._first_read_timer = None

    def _on_first_read_timeout(self):
        self._first_read_timer = None
        if self._pending_reads:
            LOG.warning("%s: still no value after %ds; answering %d waiting read(s) with a placeholder", self.name, self.FIRST_READ_WAIT_SECONDS, len(self._pending_reads))
            self._release_pending_reads(self.PENDING_VALUE)
        return False

    def _release_pending_reads(self, value):
        pending, self._pending_reads = self._pending_reads, []
        for respond in pending:
            respond(value)


class BasicInfoService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, "19f65cb7-deba-40cc-a00f-6eaa29b6ea85", True)
        self.add_characteristic(PlanesignTempCharacteristic(bus, 0, self))
        self.add_characteristic(PlanesignHostnameCharacteristic(bus, 1, self))
        self.add_characteristic(PlanesignUptimeCharacteristic(bus, 2, self))
        self.wifi_status = PlanesignWiFiStatusCharacteristic(bus, 3, self)
        self.add_characteristic(self.wifi_status)
        self.add_characteristic(PlanesignIPAddressCharacteristic(bus, 4, self))


class SystemControlService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, "312f08be-a717-40b0-9730-6d3d7c929856", True)
        self.add_characteristic(SafeCommandCharacteristic(bus, 0, self))
        self.add_characteristic(PlanesignIdentifyCharacteristic(bus, 1, self))


class ContainerControlService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, "a8e86355-accb-4ba4-a7c5-63206cab4b7b", True)
        self.add_characteristic(DockerContainerControlCharacteristic(bus, 0, self))
        self.add_characteristic(PlaneSignVersionCharacteristic(bus, 1, self))
        self.add_characteristic(DockerUpdateCheckCharacteristic(bus, 2, self))
        log_char = SystemUpdateLogCharacteristic(bus, 4, self)
        self.add_characteristic(SystemUpdateCharacteristic(bus, 3, self, log_char))
        self.add_characteristic(log_char)


class DockerUpdateCheckCharacteristic(CachedValueCharacteristic):
    UPDATE_CHECK_CHRC_UUID = "a9cc9f79-aa76-4955-aeb5-85aa9299028e"
    GHCR_TOKEN_URL = f"https://ghcr.io/token?scope=repository:{DOCKER_IMAGE_REPO}:pull&service=ghcr.io"
    GHCR_MANIFEST_URL = f"https://ghcr.io/v2/{DOCKER_IMAGE_REPO}/manifests/latest"
    # Index/list types first so GHCR answers with the multi-arch index digest, which is what
    # `docker pull` records in RepoDigests. An arch-specific manifest digest can never match
    # it, which would report "update-available" forever.
    MANIFEST_ACCEPT = "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"
    TIMEOUT_SECONDS = 8
    # Two registry round trips; keep it warm so the app's check button answers instantly.
    REFRESH_INTERVAL_SECONDS = 900
    CACHE_TTL_SECONDS = 120.0

    def __init__(self, bus, index, service):
        CachedValueCharacteristic.__init__(self, bus, index, self.UPDATE_CHECK_CHRC_UUID, service)

    def compute_value(self):
        local_digest, local_error = self._get_local_digest()
        if local_digest is None:
            return f"check failed: {local_error}"

        remote_digest, remote_error = self._get_remote_digest()
        if remote_digest is None:
            return f"check failed: {remote_error}"

        local_short = local_digest.replace("sha256:", "")[:12]
        remote_short = remote_digest.replace("sha256:", "")[:12]

        status = "up-to-date" if local_digest == remote_digest else "update-available"
        return f"{status}|local={local_short}|remote={remote_short}"

    def _get_local_digest(self):
        """Return (digest, error) for the locally cached image."""
        if shutil.which("docker") is None:
            return None, "docker not found"

        rc, stdout, stderr = run_command(["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", DOCKER_IMAGE], timeout=10, label="docker image inspect")
        if rc != 0:
            return None, stderr.splitlines()[-1] if stderr else "image not present locally"

        try:
            # Entries look like: ghcr.io/dmod/planesign@sha256:abc123...
            repo_digests = json.loads(stdout or "[]") or []
        except ValueError as exc:
            LOG.error("Could not parse RepoDigests from docker: %s", exc)
            return None, "unreadable local image metadata"

        for entry in repo_digests:
            name, _, digest = entry.partition("@")
            if digest and name.endswith(DOCKER_IMAGE_REPO):
                return digest, None
        # A locally built or `docker load`ed image has no repo digest to compare against.
        return None, "local image has no registry digest"

    def _get_remote_digest(self):
        """Return (digest, error) from GHCR without pulling the image."""
        try:
            # Step 1: Get anonymous bearer token
            token_req = urllib.request.Request(self.GHCR_TOKEN_URL, method="GET")
            with urllib.request.urlopen(token_req, timeout=self.TIMEOUT_SECONDS) as resp:
                token_data = json.loads(resp.read().decode("utf-8"))
            token = token_data.get("token", "")
            if not token:
                return None, "registry did not return a token"

            # Step 2: HEAD request to manifest endpoint
            manifest_req = urllib.request.Request(self.GHCR_MANIFEST_URL, method="HEAD")
            manifest_req.add_header("Authorization", f"Bearer {token}")
            manifest_req.add_header("Accept", self.MANIFEST_ACCEPT)
            with urllib.request.urlopen(manifest_req, timeout=self.TIMEOUT_SECONDS) as resp:
                digest = resp.headers.get("Docker-Content-Digest", "")
            return (digest, None) if digest else (None, "registry did not return a digest")
        except urllib.error.URLError as exc:
            LOG.error("GHCR digest lookup failed: %s", exc)
            return None, f"registry unreachable: {exc.reason}"
        except Exception as exc:
            LOG.exception("GHCR digest lookup failed")
            return None, str(exc)


class SystemUpdateLogCharacteristic(Characteristic):
    """Streams stdout/stderr from the update script via BLE notifications."""

    LOG_CHRC_UUID = "f63b67f9-b823-4f8f-a528-94e286cda73e"
    MAX_LOG_SIZE = 65536  # 64 KB ring buffer

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.LOG_CHRC_UUID, ["read", "notify"], service)
        self._log_buffer = ""

    def read_value(self, options):
        return self._log_buffer[-512:] if self._log_buffer else "no log"

    def append_log(self, text):
        """Append text to the log buffer and push a BLE notification."""
        self._log_buffer += text
        if len(self._log_buffer) > self.MAX_LOG_SIZE:
            self._log_buffer = self._log_buffer[-self.MAX_LOG_SIZE :]
        if self.notifying:
            self._send_notification(text)

    def clear_log(self):
        self._log_buffer = ""

    def _send_notification(self, text):
        max_chunk = 180  # stays under the 185-byte ATT payload iOS negotiates
        encoded = text.encode("utf-8", errors="replace")
        for i in range(0, len(encoded), max_chunk):
            self.notify_value(encoded[i : i + max_chunk])


class SystemUpdateCharacteristic(Characteristic):
    UPDATE_CHRC_UUID = "32d1b76b-9532-44da-9a43-3b682b8be90c"
    UPDATE_CMD = "curl -fsSL https://raw.githubusercontent.com/dmod/PlaneSign/main/docker_install_and_update.sh | sudo bash"

    def __init__(self, bus, index, service, log_characteristic=None):
        Characteristic.__init__(self, bus, index, self.UPDATE_CHRC_UUID, ["read", "write", "notify"], service)
        self._status = "idle"
        self._process = None
        self._log_char = log_characteristic

    def _set_status(self, status):
        """Update status and push a BLE notification if subscribed."""
        self._status = status
        LOG.info("System update status: %s", status)
        self.notify_value(status)

    def read_value(self, options):
        # If a process is running, check if it finished
        if self._process is not None:
            retcode = self._process.poll()
            if retcode is None:
                self._status = "updating"
            elif retcode == 0:
                self._status = "complete"
                self._process = None
            else:
                self._status = f"failed: exit code {retcode}"
                self._process = None
        return self._status

    def write_value(self, value, options):
        command = value.decode(errors="replace").strip().lower()
        if command != "update":
            LOG.warning("Ignoring unknown system update command %r", command)
            self._set_status(f"unknown command: {command}")
            return
        if self._process is not None and self._process.poll() is None:
            LOG.info("System update already in progress; ignoring duplicate request")
            self._set_status("updating")
            return

        try:
            if self._log_char:
                self._log_char.clear_log()
            LOG.info("Starting system update")
            self._process = subprocess.Popen(self.UPDATE_CMD, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            # Make stdout non-blocking for GLib polling
            fd = self._process.stdout.fileno()
            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
            self._set_status("updating")
            # Poll subprocess output every 200ms via GLib main loop
            GLib.timeout_add(200, self._poll_process_output)
        except Exception as e:
            LOG.exception("Failed to start the system update")
            self._set_status(f"failed: {e}")

    def _poll_process_output(self):
        """GLib timeout callback: read available subprocess output and stream via BLE."""
        if self._process is None:
            return False  # stop polling

        # Read all available data from the non-blocking pipe
        try:
            while True:
                data = os.read(self._process.stdout.fileno(), 4096)
                if not data:
                    break
                text = data.decode("utf-8", errors="replace")
                if self._log_char:
                    self._log_char.append_log(text)
        except OSError:
            pass  # EAGAIN — no data available yet

        # Check if the process has finished
        retcode = self._process.poll()
        if retcode is not None:
            # Drain any remaining output
            try:
                remaining = self._process.stdout.read()
                if remaining:
                    text = remaining.decode("utf-8", errors="replace")
                    if self._log_char:
                        self._log_char.append_log(text)
            except Exception:
                LOG.exception("Failed to drain the update script output")

            if retcode == 0:
                if self._log_char:
                    self._log_char.append_log("\n--- Update complete ---\n")
                self._set_status("complete")
            else:
                if self._log_char:
                    self._log_char.append_log(f"\n--- Update failed (exit code {retcode}) ---\n")
                self._set_status(f"failed: exit code {retcode}")
            self._process = None
            return False  # stop polling

        return True  # continue polling


class PlaneSignVersionCharacteristic(CachedValueCharacteristic):
    VERSION_CHRC_UUID = "8d1151e7-04b8-49e2-955a-daa50e1285e5"
    # Must be 127.0.0.1, not localhost: localhost also resolves to ::1 and nginx only
    # listens on IPv4, so half the connection attempts are wasted on a refused socket.
    VERSION_URL = "http://127.0.0.1/api/version"
    TIMEOUT_SECONDS = 5
    # The version changes when the container is updated or restarted, so keep polling
    # instead of leaving the client stuck on whatever the first read returned.
    REFRESH_INTERVAL_SECONDS = 30
    CACHE_TTL_SECONDS = 15.0

    def __init__(self, bus, index, service):
        CachedValueCharacteristic.__init__(self, bus, index, self.VERSION_CHRC_UUID, service)

    def compute_value(self):
        try:
            req = urllib.request.Request(self.VERSION_URL, method="GET")
            with urllib.request.urlopen(req, timeout=self.TIMEOUT_SECONDS) as resp:
                body = resp.read()

            # API returns a string; tolerate bytes/whitespace and decode safely.
            text = body.decode("utf-8", errors="replace").strip()
            return text or "empty response"
        except urllib.error.URLError as exc:
            # Expected whenever the container is stopped; keep it out of the error log.
            LOG.info("PlaneSign API version unavailable: %s", exc.reason)
            return f"error: {exc.reason}"
        except Exception as exc:
            LOG.exception("Version lookup failed")
            return f"error: {exc}"


class WiFiManagementService(Service):
    def __init__(self, bus, index, wifi_status_characteristic=None):
        Service.__init__(self, bus, index, "755f57c4-1d85-4676-9dfb-bafcacbb2915", True)
        self.add_characteristic(WiFiScanCharacteristic(bus, 0, self))
        self.add_characteristic(WiFiConfigCharacteristic(bus, 1, self, wifi_status_characteristic))


class WiFiConfigCharacteristic(Characteristic):
    WIFI_CONFIG_CHRC_UUID = "99945678-1234-5678-1234-56789abcdef4"

    def __init__(self, bus, index, service, wifi_status_characteristic=None):
        Characteristic.__init__(self, bus, index, self.WIFI_CONFIG_CHRC_UUID, ["write"], service)
        self._wifi_status = wifi_status_characteristic

    def start_write(self, value, options, done, fail):
        credentials = value.decode(errors="replace").strip()
        LOG.info("Received WiFi credentials (%d bytes)", len(value))
        # `nmcli connection up` routinely takes tens of seconds. Doing it inline froze every
        # GATT operation until the client gave up, and the app then retried the whole join.
        # Acknowledge the write now and report the outcome through the WiFi status value.
        run_in_background("WiFi configuration", lambda: configure_wifi(credentials), self._on_configured)
        done()

    def _on_configured(self, result):
        if self._wifi_status is not None:
            self._wifi_status.request_refresh(f"WiFi configuration finished ({result})")


class PlanesignBLEApplication(Application):
    def __init__(self, bus):
        Application.__init__(self, bus)
        basic_info = BasicInfoService(bus, 0)
        self.add_service(basic_info)
        self.add_service(WiFiManagementService(bus, 1, basic_info.wifi_status))
        self.add_service(SystemControlService(bus, 2))
        self.add_service(ContainerControlService(bus, 3))

    def warm_caches(self, reason):
        """Recompute stale cached values, e.g. as soon as a phone connects."""
        for chrc in self.get_characteristics():
            if isinstance(chrc, CachedValueCharacteristic) and chrc.REFRESH_ON_CONNECT:
                chrc.refresh_if_stale(reason)


class PlanesignBLEAdvertisement(Advertisement):
    def __init__(self, bus, index, device_name):
        Advertisement.__init__(self, bus, index, "peripheral")
        self.add_service_uuid(PLANESIGN_MASTER_UUID)
        self.add_local_name(device_name or "PlaneSign")
        self.include_tx_power = False


class PlanesignBLEFallbackAdvertisement(Advertisement):
    def __init__(self, bus, index, device_name):
        Advertisement.__init__(self, bus, index, "peripheral")
        self.add_local_name(device_name or "PlaneSign")
        self.include_tx_power = True


class PlanesignTempCharacteristic(CachedValueCharacteristic):
    CHRC_UUID = "abbd155c-e9d1-4d9d-ae9e-6871b20880e4"
    REFRESH_INTERVAL_SECONDS = 30
    CACHE_TTL_SECONDS = 10.0

    def __init__(self, bus, index, service):
        CachedValueCharacteristic.__init__(self, bus, index, self.CHRC_UUID, service)

    def compute_value(self):
        rc, stdout, stderr = run_command(["/usr/bin/vcgencmd", "measure_temp"], timeout=5, label="vcgencmd measure_temp")
        return stdout if rc == 0 and stdout else f"error: {stderr or 'vcgencmd failed'}"


class PlanesignHostnameCharacteristic(CachedValueCharacteristic):
    CHRC_UUID = "7e60d076-d3fd-496c-8460-63a0454d94d9"
    CACHE_TTL_SECONDS = 300.0

    def __init__(self, bus, index, service):
        CachedValueCharacteristic.__init__(self, bus, index, self.CHRC_UUID, service)

    def compute_value(self):
        return socket.gethostname()


class PlanesignUptimeCharacteristic(CachedValueCharacteristic):
    CHRC_UUID = "a77a6077-7302-486e-9087-853ac5899335"
    REFRESH_INTERVAL_SECONDS = 60
    CACHE_TTL_SECONDS = 15.0

    def __init__(self, bus, index, service):
        CachedValueCharacteristic.__init__(self, bus, index, self.CHRC_UUID, service)

    def compute_value(self):
        rc, stdout, stderr = run_command(["/usr/bin/uptime"], timeout=5, label="uptime")
        return stdout if rc == 0 and stdout else f"error: {stderr or 'uptime failed'}"


class PlanesignWiFiStatusCharacteristic(CachedValueCharacteristic):
    CHRC_UUID = "f2a3b4c5-6d7e-8f90-a1b2-c3d4e5f6a7b8"
    REFRESH_INTERVAL_SECONDS = 30
    CACHE_TTL_SECONDS = 10.0

    def __init__(self, bus, index, service):
        CachedValueCharacteristic.__init__(self, bus, index, self.CHRC_UUID, service)

    def compute_value(self):
        return get_current_wifi_status()


class PlanesignIPAddressCharacteristic(CachedValueCharacteristic):
    CHRC_UUID = "fed6ced8-9ef1-4b7e-9f05-07963adde32b"
    INTERFACE_PRIORITY = ("wlan0", "eth0", "wlan1", "eth1", "usb0")
    REFRESH_INTERVAL_SECONDS = 60
    CACHE_TTL_SECONDS = 15.0

    def __init__(self, bus, index, service):
        CachedValueCharacteristic.__init__(self, bus, index, self.CHRC_UUID, service)

    def compute_value(self):
        """Report the IPv4 address of the highest priority connected interface."""
        rc, stdout, stderr = run_command(["ip", "-4", "-o", "addr", "show"], timeout=5, label="ip addr show")
        if rc != 0:
            return f"error: {stderr or 'ip addr failed'}"

        addresses = {}
        for line in stdout.splitlines():
            fields = line.split()
            # Lines look like: "3: wlan0    inet 192.168.1.5/24 brd ... scope global ..."
            if len(fields) >= 4 and fields[2] == "inet":
                addresses.setdefault(fields[1], fields[3].split("/")[0])

        for interface in self.INTERFACE_PRIORITY:
            if interface in addresses:
                return addresses[interface]
        return "No IP address"


class SafeCommandCharacteristic(CachedValueCharacteristic):
    COMMAND_CHRC_UUID = "99945678-1234-5678-1234-56789abcdef2"

    # List of safe, read-only commands
    ALLOWED_COMMANDS = {"date": ["/bin/date"], "uptime": ["/usr/bin/uptime"], "temp": ["/usr/bin/vcgencmd", "measure_temp"], "hostname": ["/bin/hostname"], "disk": ["/bin/df", "-h", "/"], "memory": ["/usr/bin/free", "-h"], "reboot": ["sudo", "-n", "/usr/sbin/reboot"]}

    # The value is the last command result, so there is nothing to recompute on its own.
    CACHE_TTL_SECONDS = float("inf")
    REFRESH_ON_CONNECT = False

    def __init__(self, bus, index, service):
        CachedValueCharacteristic.__init__(self, bus, index, self.COMMAND_CHRC_UUID, service, extra_flags=["write"])

    def compute_value(self):
        return "No command executed yet"

    def start_write(self, value, options, done, fail):
        command = value.decode(errors="replace").strip()
        LOG.info("Safe command requested: %r", command)

        args = self.ALLOWED_COMMANDS.get(command)
        if args is None:
            LOG.warning("Rejected command %r: not in the allow list", command)
            self._publish_value(f"Command '{command}' not in allowed list", 0)
            done()
            return

        # Run off the main loop: `reboot` never returns and the rest can stall under load.
        run_in_background(f"safe command {command}", lambda: self._execute(args), self._on_result)
        done()

    def _execute(self, args):
        rc, stdout, stderr = run_command(args, timeout=10, label=f"safe command {args[0]}")
        if rc != 0:
            return f"Error executing command: {stderr or f'exit code {rc}'}"
        return stdout

    def _on_result(self, result):
        self._publish_value(result, 0)

class PlanesignIdentifyCharacteristic(CachedValueCharacteristic):
    IDENTIFY_CHRC_UUID = "e64fcf70-97d7-4f4e-a5b7-8ac6004f0786"
    # 127.0.0.1 rather than localhost: nginx only listens on IPv4 but localhost also
    # resolves to ::1.
    IDENTIFY_URL = "http://127.0.0.1/api/identify"
    TIMEOUT_SECONDS = 3

    # The value reflects the last identify attempt, so there is nothing to poll for.
    CACHE_TTL_SECONDS = float("inf")
    REFRESH_ON_CONNECT = False

    def __init__(self, bus, index, service):
        CachedValueCharacteristic.__init__(self, bus, index, self.IDENTIFY_CHRC_UUID, service, extra_flags=["write"])

    def compute_value(self):
        return "idle"

    def start_write(self, value, options, done, fail):
        command = value.decode(errors="replace").strip()
        if command != "identify":
            LOG.warning("Rejected identify command %r", command)
            self._publish_value(f"Command '{command}' not in allowed list", 0)
            done()
            return

        run_in_background("identify request", self._trigger_identify, lambda result: self._publish_value(result, 0))
        done()

    def _trigger_identify(self):
        try:
            req = urllib.request.Request(self.IDENTIFY_URL, method="GET")
            # urlopen raises for >=400, so reaching here means the sign accepted the request.
            with urllib.request.urlopen(req, timeout=self.TIMEOUT_SECONDS):
                return "ok"
        except urllib.error.URLError as exc:
            LOG.warning("Identify request failed: %s", exc.reason)
            return f"error: {exc.reason}"
        except Exception as exc:
            LOG.exception("Identify request failed")
            return f"error: {exc}"


class DockerContainerControlCharacteristic(CachedValueCharacteristic):
    DOCKER_CONTAINER_CONTROL_UUID = "29352a73-3108-4ecc-9440-57b5a8a5c027"
    ALLOWED_COMMANDS = {"start", "stop"}
    # The container is the thing users most often check, so keep the status warm and push
    # changes instead of making every read pay for two `docker` invocations.
    REFRESH_INTERVAL_SECONDS = 30
    CACHE_TTL_SECONDS = 5.0

    def __init__(self, bus, index, service):
        CachedValueCharacteristic.__init__(self, bus, index, self.DOCKER_CONTAINER_CONTROL_UUID, service, extra_flags=["write"])

    def compute_value(self):
        return self._get_container_status()

    def start_write(self, value, options, done, fail):
        command = value.decode(errors="replace").strip().lower()
        LOG.info("Docker container command: %r", command)

        if command not in self.ALLOWED_COMMANDS:
            LOG.warning("Rejected docker command %r: not in the allow list", command)
            self._publish_value(f"Command '{command}' not in allowed list", 0)
            done()
            return

        # `docker kill`/`docker start` take seconds; the reply must not wait for them.
        run_in_background(f"docker {command}", lambda: self._run_docker_lifecycle(command), lambda result: self._publish_value(result, 0))
        done()

    def _docker_available(self):
        return shutil.which("docker") is not None

    def _run_docker_lifecycle(self, command):
        if not self._docker_available():
            return "docker not found"

        # Client API uses "stop", but we intentionally force-stop via `docker kill`.
        docker_command = "kill" if command == "stop" else command

        rc, stdout, stderr = run_command(["docker", docker_command, DOCKER_CONTAINER_NAME], timeout=20, label=f"docker {docker_command}")
        if rc != 0:
            return f"docker {docker_command} failed: {stderr or stdout or 'unknown error'}"

        # After lifecycle operations, return updated status for convenience.
        return self._get_container_status()

    def _get_container_status(self):
        if not self._docker_available():
            return "docker not found"

        # Prefer inspect for a precise status.
        rc, stdout, stderr = run_command(["docker", "inspect", "-f", "{{.Name}}|{{.State.Status}}|{{.State.Running}}|{{.Id}}", DOCKER_CONTAINER_NAME], timeout=15, label="docker inspect")
        if rc == 0 and stdout:
            # stdout like: /PlaneSignRuntime|running|true|<id>
            parts = stdout.split("|")
            if len(parts) >= 4:
                name, state, running, cid = parts[0], parts[1], parts[2], parts[3]
                return f"{name.lstrip('/')} status={state} running={running} id={cid[:12]}"
            return stdout

        # Fallback to ps -a filtered by name.
        rc2, stdout2, stderr2 = run_command(["docker", "ps", "-a", "--filter", f"name=^{DOCKER_CONTAINER_NAME}$", "--format", "{{.Names}}|{{.Status}}|{{.ID}}"], timeout=15, label="docker ps")
        if rc2 == 0 and stdout2:
            line = stdout2.splitlines()[0]
            parts = line.split("|")
            if len(parts) >= 3:
                name, status, cid = parts[0], parts[1], parts[2]
                return f"{name} {status} id={cid}"
            return stdout2

        LOG.error("Could not determine container status: inspect=%r ps=%r", stderr, stderr2)
        return f"status unavailable: {stderr or stderr2 or 'unknown error'}"


class ClientConnectionWatcher:
    """Logs central connections and warms every cached value the moment a phone attaches."""

    def __init__(self, bus, app):
        self._app = app
        self._connected = set()
        bus.add_signal_receiver(self._on_properties_changed, dbus_interface=DBUS_PROP_IFACE, signal_name="PropertiesChanged", arg0=DEVICE_IFACE, path_keyword="path")

    def _on_properties_changed(self, interface, changed, invalidated, path=None):
        if "Connected" not in changed:
            return
        address = str(path).rsplit("/", 1)[-1]
        if changed["Connected"]:
            self._connected.add(address)
            LOG.info("Central %s connected (%d connected)", address, len(self._connected))
            self._app.warm_caches(f"{address} connected")
        else:
            self._connected.discard(address)
            LOG.info("Central %s disconnected (%d connected)", address, len(self._connected))


def wait_for_adapter_powered(bus, adapter, timeout_seconds=15):
    props = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, adapter), DBUS_PROP_IFACE)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            powered = props.Get(ADAPTER_IFACE, "Powered")
            if powered:
                return True
            props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(True))
        except Exception as exc:
            LOG.warning("Bluetooth power wait failed: %s", exc)
        time.sleep(0.5)
    return False


class WiFiScanCharacteristic(CachedValueCharacteristic):
    WIFI_SCAN_CHRC_UUID = "99945678-1234-5678-1234-56789abcdef3"
    CACHE_TTL_SECONDS = 60.0
    PENDING_VALUE = "No networks found"
    # Deliberately not refreshed on connect: the app reads every readable characteristic as
    # soon as it attaches, and a scan on the Pi's shared WiFi/Bluetooth radio degrades the
    # link that read is travelling over.
    REFRESH_ON_CONNECT = False

    def __init__(self, bus, index, service):
        CachedValueCharacteristic.__init__(self, bus, index, self.WIFI_SCAN_CHRC_UUID, service)

    def compute_value(self):
        return scan_wifi()


def main():
    global mainloop
    configure_logging()
    LOG.info("Starting PlaneSign BLE service (pid %d, uid %d)", os.getpid(), os.geteuid())

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    adapter = find_adapter_wait(bus, timeout_seconds=15)
    if not adapter:
        LOG.error("BLE adapter not found after waiting; exiting so systemd restarts us")
        return

    # Set device name consistently
    device_name = f"PlaneSign-BLE-{get_mac_id()}"

    # Set the Bluetooth device name and wait for the adapter to settle.
    set_adapter_name(bus, adapter, device_name)
    if not wait_for_adapter_powered(bus, adapter, timeout_seconds=15):
        LOG.warning("Bluetooth adapter did not become powered in time")

    service_manager = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, adapter), GATT_MANAGER_IFACE)
    ad_manager = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, adapter), LE_ADVERTISING_MANAGER_IFACE)

    app = PlanesignBLEApplication(bus)
    adv = PlanesignBLEAdvertisement(bus, 0, device_name)

    mainloop = GLib.MainLoop()
    set_mainloop(mainloop)
    ClientConnectionWatcher(bus, app)
    ad_state = {"count": 0, "fallback": False, "adv": adv}

    def on_ad_registered():
        register_ad_cb()
        LOG.info("Advertising as %s", device_name)

    def on_ad_error(error):
        ad_state["count"] += 1
        LOG.error("Advertisement registration error (attempt %d): %s", ad_state["count"], error)
        if not ad_state["fallback"]:
            LOG.warning("Falling back to a minimal advertisement payload")
            ad_state["fallback"] = True
            ad_state["count"] = 0
            ad_state["adv"] = PlanesignBLEFallbackAdvertisement(bus, 1, device_name)
            GLib.timeout_add_seconds(2, try_register_ad)
            return
        if ad_state["count"] < 5:
            LOG.info("Retrying advertisement registration in 2 seconds")
            GLib.timeout_add_seconds(2, try_register_ad)
        else:
            LOG.error("Advertisement registration failed after retries; exiting")
            mainloop.quit()

    def try_register_ad():
        try:
            adv_obj = ad_state["adv"]
            LOG.info("Attempting advertisement registration (attempt %d)", ad_state["count"] + 1)
            ad_manager.RegisterAdvertisement(adv_obj.get_path(), {}, reply_handler=on_ad_registered, error_handler=on_ad_error)
        except Exception:
            LOG.exception("Synchronous advertisement registration call failed")
            ad_state["count"] += 1
            if ad_state["count"] < 5:
                GLib.timeout_add_seconds(2, try_register_ad)
            else:
                LOG.error("Advertisement registration failed after retries; exiting")
                mainloop.quit()
        return False

    def on_app_registered():
        register_app_cb()
        try_register_ad()

    service_manager.RegisterApplication(app.get_path(), {}, reply_handler=on_app_registered, error_handler=register_app_error_cb)
    try:
        mainloop.run()
    except KeyboardInterrupt:
        LOG.info("Interrupted; releasing the advertisement")
        adv.Release()
    finally:
        WORKERS.shutdown(wait=False)
        LOG.info("PlaneSign BLE service stopped")


def get_mac_id(interface="wlan0"):
    try:
        mac_path = f"/sys/class/net/{interface}/address"
        if not os.path.exists(mac_path):
            LOG.warning("No MAC address available for %s; using UNKNOWN in the device name", interface)
            return "UNKNOWN"

        with open(mac_path, "r", encoding="utf-8") as f:
            mac_address = f.read().strip()
        return mac_address.replace(":", "").upper()[-4:]
    except Exception:
        LOG.exception("Could not read the %s MAC address", interface)
        return "UNKNOWN"


if __name__ == "__main__":
    main()
