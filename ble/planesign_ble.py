import dbus, dbus.mainloop.glib
import fcntl
import json
import os
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
from gi.repository import GLib
from gatt import Application, Advertisement, Service, Characteristic
from gatt import find_adapter, set_adapter_name, register_app_cb, register_app_error_cb, register_ad_cb, register_ad_error_cb
from wifi import get_current_wifi_status, scan_wifi, configure_wifi

BLUEZ_SERVICE_NAME =           'org.bluez'
DBUS_OM_IFACE =                'org.freedesktop.DBus.ObjectManager'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
GATT_MANAGER_IFACE =           'org.bluez.GattManager1'
GATT_CHRC_IFACE =              'org.bluez.GattCharacteristic1'
PLANESIGN_MASTER_UUID =        '3d951a35-76c5-4207-a150-2d0cf7d2bfdd'
DOCKER_CONTAINER_NAME =        'PlaneSignRuntime'
DOCKER_IMAGE =                 'ghcr.io/dmod/planesign:latest'
DOCKER_IMAGE_REPO =            'dmod/planesign'
mainloop = None

class BasicInfoService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, '19f65cb7-deba-40cc-a00f-6eaa29b6ea85', True)
        self.add_characteristic(PlanesignTempCharacteristic(bus, 0, self))
        self.add_characteristic(PlanesignHostnameCharacteristic(bus, 1, self))
        self.add_characteristic(PlanesignUptimeCharacteristic(bus, 2, self))
        self.add_characteristic(PlanesignWiFiStatusCharacteristic(bus, 3, self))
        self.add_characteristic(PlanesignIPAddressCharacteristic(bus, 4, self))

class SystemControlService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, '312f08be-a717-40b0-9730-6d3d7c929856', True)
        self.add_characteristic(SafeCommandCharacteristic(bus, 0, self))

class ContainerControlService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, 'a8e86355-accb-4ba4-a7c5-63206cab4b7b', True)
        self.add_characteristic(DockerContainerControlCharacteristic(bus, 0, self))
        self.add_characteristic(PlaneSignVersionCharacteristic(bus, 1, self))
        self.add_characteristic(DockerUpdateCheckCharacteristic(bus, 2, self))
        log_char = SystemUpdateLogCharacteristic(bus, 4, self)
        self.add_characteristic(SystemUpdateCharacteristic(bus, 3, self, log_char))
        self.add_characteristic(log_char)

class DockerUpdateCheckCharacteristic(Characteristic):
    UPDATE_CHECK_CHRC_UUID = 'a9cc9f79-aa76-4955-aeb5-85aa9299028e'
    GHCR_TOKEN_URL = f'https://ghcr.io/token?scope=repository:{DOCKER_IMAGE_REPO}:pull&service=ghcr.io'
    GHCR_MANIFEST_URL = f'https://ghcr.io/v2/{DOCKER_IMAGE_REPO}/manifests/latest'
    TIMEOUT_SECONDS = 8

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.UPDATE_CHECK_CHRC_UUID, ['read'], service)

    def ReadValue(self, options):
        result = self._check_for_update()
        print('DockerUpdateCheckCharacteristic Read: ' + result)
        return [dbus.Byte(x.encode()) for x in result]

    def _check_for_update(self):
        try:
            local_digest = self._get_local_digest()
            if local_digest is None:
                return 'check failed: could not get local digest'

            remote_digest = self._get_remote_digest()
            if remote_digest is None:
                return 'check failed: could not get remote digest'

            local_short = local_digest.replace('sha256:', '')[:12]
            remote_short = remote_digest.replace('sha256:', '')[:12]

            if local_digest == remote_digest:
                return f'up-to-date|local={local_short}|remote={remote_short}'
            else:
                return f'update-available|local={local_short}|remote={remote_short}'
        except Exception as e:
            return f'check failed: {e}'

    def _get_local_digest(self):
        """Get the repo digest of the locally cached image."""
        try:
            completed = subprocess.run(
                ['docker', 'inspect', '--format', '{{index .RepoDigests 0}}', DOCKER_IMAGE],
                capture_output=True, text=True, timeout=5, check=False,
            )
            if completed.returncode != 0:
                return None
            # Output like: ghcr.io/dmod/planesign@sha256:abc123...
            repo_digest = completed.stdout.strip()
            if '@' in repo_digest:
                return repo_digest.split('@', 1)[1]
            return repo_digest
        except Exception as e:
            print(f'_get_local_digest error: {e}')
            return None

    def _get_remote_digest(self):
        """Fetch the remote manifest digest from GHCR without pulling the image."""
        try:
            # Step 1: Get anonymous bearer token
            token_req = urllib.request.Request(self.GHCR_TOKEN_URL, method='GET')
            with urllib.request.urlopen(token_req, timeout=self.TIMEOUT_SECONDS) as resp:
                token_data = json.loads(resp.read().decode('utf-8'))
            token = token_data.get('token', '')
            if not token:
                return None

            # Step 2: HEAD request to manifest endpoint
            manifest_req = urllib.request.Request(self.GHCR_MANIFEST_URL, method='HEAD')
            manifest_req.add_header('Authorization', f'Bearer {token}')
            manifest_req.add_header('Accept', (
                'application/vnd.docker.distribution.manifest.v2+json, '
                'application/vnd.docker.distribution.manifest.list.v2+json, '
                'application/vnd.oci.image.index.v1+json'
            ))
            with urllib.request.urlopen(manifest_req, timeout=self.TIMEOUT_SECONDS) as resp:
                digest = resp.headers.get('Docker-Content-Digest', '')
            return digest if digest else None
        except Exception as e:
            print(f'_get_remote_digest error: {e}')
            return None

class SystemUpdateLogCharacteristic(Characteristic):
    """Streams stdout/stderr from the update script via BLE notifications."""
    LOG_CHRC_UUID = 'f63b67f9-b823-4f8f-a528-94e286cda73e'
    MAX_LOG_SIZE = 65536  # 64 KB ring buffer

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.LOG_CHRC_UUID, ['read', 'notify'], service)
        self._log_buffer = ''
        self._notifying = False

    def ReadValue(self, options):
        chunk = self._log_buffer[-512:] if self._log_buffer else 'no log'
        return [dbus.Byte(x.encode()) for x in chunk]

    def StartNotify(self):
        if self._notifying:
            return
        self._notifying = True
        print('SystemUpdateLogCharacteristic: notifications enabled')

    def StopNotify(self):
        self._notifying = False
        print('SystemUpdateLogCharacteristic: notifications disabled')

    def append_log(self, text):
        """Append text to the log buffer and push a BLE notification."""
        self._log_buffer += text
        if len(self._log_buffer) > self.MAX_LOG_SIZE:
            self._log_buffer = self._log_buffer[-self.MAX_LOG_SIZE:]
        if self._notifying:
            self._send_notification(text)

    def clear_log(self):
        self._log_buffer = ''

    def _send_notification(self, text):
        max_chunk = 480  # conservative BLE MTU-safe size
        encoded = text.encode('utf-8', errors='replace')
        for i in range(0, len(encoded), max_chunk):
            chunk = encoded[i:i + max_chunk]
            value = dbus.Array([dbus.Byte(b) for b in chunk], signature='y')
            self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': value}, [])


class SystemUpdateCharacteristic(Characteristic):
    UPDATE_CHRC_UUID = '32d1b76b-9532-44da-9a43-3b682b8be90c'
    UPDATE_CMD = 'curl -fsSL https://raw.githubusercontent.com/dmod/PlaneSign/main/docker_install_and_update.sh | sudo -u pi bash'

    def __init__(self, bus, index, service, log_characteristic=None):
        Characteristic.__init__(self, bus, index, self.UPDATE_CHRC_UUID, ['read', 'write', 'notify'], service)
        self._status = 'idle'
        self._process = None
        self._log_char = log_characteristic
        self._notifying = False

    def StartNotify(self):
        if self._notifying:
            return
        self._notifying = True

    def StopNotify(self):
        self._notifying = False

    def _set_status(self, status):
        """Update status and push a BLE notification if subscribed."""
        self._status = status
        print('SystemUpdateCharacteristic status: ' + status)
        if self._notifying:
            value = dbus.Array([dbus.Byte(b) for b in status.encode('utf-8')], signature='y')
            self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': value}, [])

    def ReadValue(self, options):
        # If a process is running, check if it finished
        if self._process is not None:
            retcode = self._process.poll()
            if retcode is None:
                self._status = 'updating'
            elif retcode == 0:
                self._status = 'complete'
                self._process = None
            else:
                self._status = f'failed: exit code {retcode}'
                self._process = None
        print('SystemUpdateCharacteristic Read: ' + self._status)
        return [dbus.Byte(x.encode()) for x in self._status]

    def WriteValue(self, value, options):
        command = bytes(value).decode(errors='replace').strip().lower()
        print('SystemUpdateCharacteristic Write: ' + command)
        if command != 'update':
            self._set_status(f"unknown command: {command}")
            return
        if self._process is not None and self._process.poll() is None:
            self._set_status('updating')  # already in progress
            return
        try:
            if self._log_char:
                self._log_char.clear_log()
            self._process = subprocess.Popen(
                self.UPDATE_CMD,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            # Make stdout non-blocking for GLib polling
            fd = self._process.stdout.fileno()
            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
            self._set_status('updating')
            # Poll subprocess output every 200ms via GLib main loop
            GLib.timeout_add(200, self._poll_process_output)
        except Exception as e:
            self._set_status(f'failed: {e}')

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
                text = data.decode('utf-8', errors='replace')
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
                    text = remaining.decode('utf-8', errors='replace')
                    if self._log_char:
                        self._log_char.append_log(text)
            except Exception as e:
                print(f'_poll_process_output drain error: {e}')

            if retcode == 0:
                if self._log_char:
                    self._log_char.append_log('\n--- Update complete ---\n')
                self._set_status('complete')
            else:
                if self._log_char:
                    self._log_char.append_log(f'\n--- Update failed (exit code {retcode}) ---\n')
                self._set_status(f'failed: exit code {retcode}')
            self._process = None
            return False  # stop polling

        return True  # continue polling


class PlaneSignVersionCharacteristic(Characteristic):
    VERSION_CHRC_UUID = '8d1151e7-04b8-49e2-955a-daa50e1285e5'
    VERSION_URL = 'http://localhost/api/version'
    TIMEOUT_SECONDS = 2

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.VERSION_CHRC_UUID, ['read'], service)

    def ReadValue(self, options):
        version = self._fetch_version()
        print('PlaneSignVersionCharacteristic Read: ' + version)
        return [dbus.Byte(x.encode()) for x in version]

    def _fetch_version(self):
        try:
            req = urllib.request.Request(self.VERSION_URL, method='GET')
            with urllib.request.urlopen(req, timeout=self.TIMEOUT_SECONDS) as resp:
                body = resp.read()

            # API returns a string; tolerate bytes/whitespace and decode safely.
            text = body.decode('utf-8', errors='replace').strip()
            return text or 'empty response'
        except Exception as e:
            return f'error: {e}'

class WiFiManagementService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, '755f57c4-1d85-4676-9dfb-bafcacbb2915', True)
        self.add_characteristic(WiFiScanCharacteristic(bus, 0, self))
        self.add_characteristic(WiFiConfigCharacteristic(bus, 1, self))

class WiFiConfigCharacteristic(Characteristic):
    WIFI_CONFIG_CHRC_UUID = '99945678-1234-5678-1234-56789abcdef4'

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.WIFI_CONFIG_CHRC_UUID, ['write'], service)
        self.value = []

    def WriteValue(self, value, options):
        credentials = bytes(value).decode().strip()
        print('WiFiConfigCharacteristic Write: Received credentials')
        try:
            configure_wifi(credentials)
        except Exception as e:
            print(f'WiFiConfigCharacteristic error: {e}')
            raise

class PlanesignBLEApplication(Application):
    def __init__(self, bus):
        Application.__init__(self, bus)
        self.add_service(BasicInfoService(bus, 0))
        self.add_service(WiFiManagementService(bus, 1))
        self.add_service(SystemControlService(bus, 2))
        self.add_service(ContainerControlService(bus, 3))

class PlanesignBLEAdvertisement(Advertisement):
    def __init__(self, bus, index, device_name):
        Advertisement.__init__(self, bus, index, 'peripheral')
        self.add_service_uuid(PLANESIGN_MASTER_UUID)
        self.add_local_name(device_name)
        self.include_tx_power = True

class PlanesignTempCharacteristic(Characteristic):
    CHRC_UUID = 'abbd155c-e9d1-4d9d-ae9e-6871b20880e4'

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.CHRC_UUID, ['read'], service)

    def ReadValue(self, options):
        try:
            temperature = subprocess.check_output('/usr/bin/vcgencmd measure_temp', shell=True, timeout=5).decode("utf-8").strip()
        except Exception as e:
            temperature = f'error: {e}'
        print('Temp Read: ' + temperature)

        return [dbus.Byte(x.encode()) for x in temperature]
    
class PlanesignHostnameCharacteristic(Characteristic):
    CHRC_UUID = '7e60d076-d3fd-496c-8460-63a0454d94d9'

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.CHRC_UUID, ['read'], service)

    def ReadValue(self, options):
        try:
            hostname = subprocess.check_output('/bin/hostname', shell=True, timeout=5).decode("utf-8").strip()
        except Exception as e:
            hostname = f'error: {e}'
        print('Hostname Read: ' + hostname)

        return [dbus.Byte(x.encode()) for x in hostname]
    
class PlanesignUptimeCharacteristic(Characteristic):
    CHRC_UUID = 'a77a6077-7302-486e-9087-853ac5899335'

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.CHRC_UUID, ['read'], service)

    def ReadValue(self, options):
        try:
            uptime = subprocess.check_output('/usr/bin/uptime', shell=True, timeout=5).decode("utf-8").strip()
        except Exception as e:
            uptime = f'error: {e}'
        print('Uptime Read: ' + uptime)

        return [dbus.Byte(x.encode()) for x in uptime]

class PlanesignWiFiStatusCharacteristic(Characteristic):
    CHRC_UUID = 'f2a3b4c5-6d7e-8f90-a1b2-c3d4e5f6a7b8'

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.CHRC_UUID, ['read'], service)

    def ReadValue(self, options):
        wifi_status = get_current_wifi_status()
        print('WiFi Status Read: ' + wifi_status)
        return [dbus.Byte(x.encode()) for x in wifi_status]

class PlanesignIPAddressCharacteristic(Characteristic):
    CHRC_UUID = 'fed6ced8-9ef1-4b7e-9f05-07963adde32b'

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.CHRC_UUID, ['read'], service)

    def ReadValue(self, options):
        ip_address = self._get_ip_address()
        print('IP Address Read: ' + ip_address)
        return [dbus.Byte(x.encode()) for x in ip_address]

    def _get_ip_address(self):
        """Get the IP address from the first connected network interface."""
        for interface in ['wlan0', 'eth0', 'wlan1', 'eth1', 'usb0']:
            try:
                cmd = f"ip -4 addr show {interface} | grep -oP '(?<=inet\\s)\\d+(\\.\\d+){{3}}'"
                ip = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode().strip().split('\n')[0]
                if ip:
                    return ip
            except subprocess.CalledProcessError:
                continue
        return "No IP address"

class SafeCommandCharacteristic(Characteristic):
    COMMAND_CHRC_UUID = '99945678-1234-5678-1234-56789abcdef2'

    # List of safe, read-only commands
    ALLOWED_COMMANDS = {
        'date': '/bin/date',
        'uptime': '/usr/bin/uptime',
        'temp': '/usr/bin/vcgencmd measure_temp',
        'hostname': '/bin/hostname',
        'disk': '/bin/df -h /',
        'memory': '/usr/bin/free -h',
        'reboot': 'sudo /usr/sbin/reboot'
    }

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.COMMAND_CHRC_UUID, ['read', 'write'], service)
        self.value = []
        self.last_result = "No command executed yet"

    def ReadValue(self, options):
        print('SafeCommandCharacteristic Read: ' + self.last_result)
        return [dbus.Byte(x.encode()) for x in self.last_result]

    def WriteValue(self, value, options):
        command = bytes(value).decode().strip()
        print('SafeCommandCharacteristic Write: ' + command)

        if command in self.ALLOWED_COMMANDS:
            try:
                result = subprocess.check_output(
                    self.ALLOWED_COMMANDS[command], 
                    shell=True,
                    timeout=5
                ).decode('utf-8').strip()
                self.last_result = result
            except Exception as e:
                self.last_result = f"Error executing command: {str(e)}"
        else:
            self.last_result = f"Command '{command}' not in allowed list"

class DockerContainerControlCharacteristic(Characteristic):
    DOCKER_CONTAINER_CONTROL_UUID = '29352a73-3108-4ecc-9440-57b5a8a5c027'

    ALLOWED_COMMANDS = {
        'start',
        'stop',
    }

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.DOCKER_CONTAINER_CONTROL_UUID, ['read', 'write'], service)
        self.value = []
        self.last_result = "No docker command executed yet"

    def ReadValue(self, options):
        # Always return live container status (client reads immediately after connect).
        try:
            status = self._get_container_status()
            self.last_result = status
        except Exception as e:
            self.last_result = f"Error: {e}"

        print('DockerContainerControlCharacteristic Read: ' + self.last_result)
        return [dbus.Byte(x.encode()) for x in self.last_result]

    def WriteValue(self, value, options):
        command = bytes(value).decode(errors='replace').strip().lower()
        print('DockerContainerControlCharacteristic Write: ' + command)

        if command not in self.ALLOWED_COMMANDS:
            self.last_result = f"Command '{command}' not in allowed list"
            return

        try:
            self.last_result = self._run_docker_lifecycle(command)
        except Exception as e:
            self.last_result = f"Error: {e}"

    def _docker_available(self):
        return shutil.which('docker') is not None

    def _run(self, args, timeout=8):
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        stdout = (completed.stdout or '').strip()
        stderr = (completed.stderr or '').strip()
        return completed.returncode, stdout, stderr

    def _run_docker_lifecycle(self, command):
        if not self._docker_available():
            return "docker not found"

        # Client API uses "stop", but we intentionally force-stop via `docker kill`.
        docker_command = 'kill' if command == 'stop' else command

        docker_args = ['docker', docker_command, DOCKER_CONTAINER_NAME]
        rc, stdout, stderr = self._run(docker_args)
        if rc != 0:
            return f"docker {docker_command} failed: {stderr or stdout or 'unknown error'}"

        # After lifecycle operations, return updated status for convenience.
        status = self._get_container_status()
        return f"ok: {stdout or command}; {status}"

    def _get_container_status(self):
        if not self._docker_available():
            return "docker not found"

        # Prefer inspect for a precise status.
        rc, stdout, stderr = self._run(
            ['docker', 'inspect', '-f', '{{.Name}}|{{.State.Status}}|{{.State.Running}}|{{.Id}}', DOCKER_CONTAINER_NAME]
        )
        if rc == 0 and stdout:
            # stdout like: /PlaneSignRuntime|running|true|<id>
            parts = stdout.split('|')
            if len(parts) >= 4:
                name, state, running, cid = parts[0], parts[1], parts[2], parts[3]
                cid_short = cid[:12]
                return f"{name.lstrip('/')} status={state} running={running} id={cid_short}"
            return stdout

        # Fallback to ps -a filtered by name.
        rc2, stdout2, stderr2 = self._run(
            ['docker', 'ps', '-a', '--filter', f"name=^{DOCKER_CONTAINER_NAME}$", '--format', '{{.Names}}|{{.Status}}|{{.ID}}']
        )
        if rc2 == 0 and stdout2:
            line = stdout2.splitlines()[0]
            parts = line.split('|')
            if len(parts) >= 3:
                name, status, cid = parts[0], parts[1], parts[2]
                return f"{name} {status} id={cid}"
            return stdout2

        return f"status unavailable: {stderr or stderr2 or 'unknown error'}"

class WiFiScanCharacteristic(Characteristic):
    WIFI_SCAN_CHRC_UUID = '99945678-1234-5678-1234-56789abcdef3'

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.WIFI_SCAN_CHRC_UUID, ['read'], service)

    def ReadValue(self, options):
        print('WiFiScanCharacteristic Read requested - scanning...')
        scan_result = scan_wifi()
        print(f'Scan result size: {len(scan_result)}')
        return [dbus.Byte(x.encode()) for x in scan_result]

def main():
    global mainloop
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    adapter = find_adapter(bus)
    if not adapter:
        print('BLE adapter not found')
        return
    
    # Set device name consistently
    device_name = f"PlaneSign-BLE-{get_mac_id()}"
    
    # Set the Bluetooth device name
    set_adapter_name(bus, adapter, device_name)

    service_manager = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, adapter), GATT_MANAGER_IFACE)
    ad_manager = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, adapter), LE_ADVERTISING_MANAGER_IFACE)

    app = PlanesignBLEApplication(bus)
    adv = PlanesignBLEAdvertisement(bus, 0, device_name)

    mainloop = GLib.MainLoop()

    service_manager.RegisterApplication(app.get_path(), {},
                                        reply_handler=register_app_cb,
                                        error_handler=register_app_error_cb)
    ad_manager.RegisterAdvertisement(adv.get_path(), {},
                                     reply_handler=register_ad_cb,
                                     error_handler=register_ad_error_cb)
    try:
        mainloop.run()
    except KeyboardInterrupt:
        adv.Release()

def get_mac_id(interface='wlan0'):
    cmd = f"cat /sys/class/net/{interface}/address"
    mac_address = subprocess.check_output(cmd, shell=True, timeout=5).decode().strip()
    return mac_address.replace(":", "").upper()[-4:]

if __name__ == '__main__':
    main()