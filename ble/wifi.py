import logging
import os
import time

from gatt import run_command

logger = logging.getLogger("planesign.ble.wifi")

WIFI_INTERFACE = "wlan0"
MAX_NETWORKS = 10
# The kernel expires cached BSS entries quickly, so a dump that only contains the
# associated AP (or nothing) means a real scan is needed.
MIN_CACHED_NETWORKS = 3


def _needs_sudo():
    """The service runs as root, where calling sudo only adds latency and failure modes."""
    return os.geteuid() != 0


class WiFiNetwork:
    def __init__(self, ssid, signal, encrypted):
        self.ssid = ssid
        self.signal = signal
        self.encrypted = encrypted

    def get_signal_int(self):
        try:
            return int(float(self.signal))
        except (ValueError, TypeError):
            return -100  # Very weak signal for sorting

    def __str__(self):
        return f"{self.ssid}|{self.signal}|{self.encrypted}"


def get_current_wifi_status():
    """Return "Connected|SSID|signal", "Disconnected|None|0" or "Error|...|0"."""
    rc, stdout, stderr = run_command(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi", "list", "--rescan", "no"], timeout=10, label="nmcli wifi list")
    if rc != 0:
        return f"Error|{stderr or 'Unable to get WiFi status'}|0"

    for line in stdout.split("\n"):
        if not line.startswith("yes:"):
            continue
        parts = line.split(":")
        if len(parts) >= 3:
            ssid = parts[1] or "Hidden Network"
            signal = parts[2] or "0"
            logger.debug("Connected to %s at signal %s", ssid, signal)
            return f"Connected|{ssid}|{signal}"

    logger.debug("nmcli reports no active WiFi connection")
    return "Disconnected|None|0"


def _parse_iw_scan(output):
    """Parse `iw scan` / `iw scan dump` output into WiFiNetwork objects."""
    networks = []
    current_network = {}

    for line in output.split("\n"):
        line = line.strip()
        if "BSS" in line and "(" in line:  # New network found
            if current_network.get("ssid"):  # Save previous network if it had an SSID
                networks.append(WiFiNetwork(ssid=current_network["ssid"], signal=current_network.get("signal", "N/A"), encrypted=current_network.get("encrypted", "no")))
            current_network = {"encrypted": "no"}  # Start with assumption of open network
        elif "SSID:" in line:
            ssid = line.split("SSID:", 1)[1].strip()
            if ssid:  # Only store non-empty SSIDs
                current_network["ssid"] = ssid
        elif "signal:" in line:
            current_network["signal"] = line.split("signal:", 1)[1].strip().split()[0]  # Gets the dBm value
        elif "Privacy:" in line or "WPA" in line or "WEP" in line or "RSN" in line:
            # If we see any privacy/security indicators, mark as encrypted
            current_network["encrypted"] = "yes"

    # Add the last network if it exists
    if current_network.get("ssid"):
        networks.append(WiFiNetwork(ssid=current_network["ssid"], signal=current_network.get("signal", "N/A"), encrypted=current_network.get("encrypted", "no")))

    return networks


def _deduplicate(networks):
    """Group by SSID: dual-band, multiple APs and security modes all produce duplicates."""
    unique_networks = {}
    for network in networks:
        if network.ssid not in unique_networks:
            unique_networks[network.ssid] = network
            continue
        current = unique_networks[network.ssid]
        # Prefer 2.4GHz for better range, fall back to stronger signal
        signal_diff = network.get_signal_int() - current.get_signal_int()
        if signal_diff > 0 or (abs(signal_diff) <= 15 and current.get_signal_int() > -40):
            unique_networks[network.ssid] = network
    return unique_networks


def scan_wifi():
    """Return up to MAX_NETWORKS nearby networks as "SSID|signal|encrypted" lines.

    Reads the kernel's cached scan table first because a live `iw scan` takes about four
    seconds and, since the Pi shares one radio between WiFi and Bluetooth, degrades the BLE
    link while it runs. Callers must invoke this from a worker thread.
    """
    sudo = ["sudo", "-n"] if _needs_sudo() else []
    started = time.monotonic()

    rc, stdout, _ = run_command(sudo + ["iw", "dev", WIFI_INTERFACE, "scan", "dump"], timeout=10, label="iw scan dump")
    networks = _parse_iw_scan(stdout) if rc == 0 else []
    source = "cached scan table"

    if len(networks) < MIN_CACHED_NETWORKS:
        logger.info("Cached scan table held only %d network(s) (rc=%s); running a live scan", len(networks), rc)
        rc, stdout, stderr = run_command(sudo + ["iw", "dev", WIFI_INTERFACE, "scan"], timeout=25, label="iw scan")
        if rc != 0:
            logger.error("WiFi scan failed: %s", stderr or stdout or "unknown error")
            return f"Error scanning WiFi: {stderr or 'scan failed'}"
        networks = _parse_iw_scan(stdout)
        source = "live scan"

    unique_networks = _deduplicate(networks)
    top_networks = sorted(unique_networks.values(), key=lambda net: net.get_signal_int(), reverse=True)[:MAX_NETWORKS]

    logger.info("WiFi scan (%s) took %.0f ms: %d seen, %d unique, returning %d", source, (time.monotonic() - started) * 1000, len(networks), len(unique_networks), len(top_networks))
    return "\n".join(str(network) for network in top_networks) if top_networks else "No networks found"


def configure_wifi(credentials):
    """Join the given network, returning a status string. Never raises.

    `nmcli connection up` regularly takes tens of seconds, so this must only be called from
    a worker thread and never from the BLE main loop.
    """
    if "|" not in credentials:
        logger.error("WiFi credentials were not in the expected 'SSID|PASSWORD' format")
        return "error: invalid format, expected 'SSID|PASSWORD'"

    ssid, password = credentials.split("|", 1)
    ssid = ssid.strip()
    if not ssid:
        return "error: missing SSID"

    sudo = ["sudo", "-n"] if _needs_sudo() else []
    logger.info("Configuring WiFi for SSID %r (%s network)", ssid, "secured" if password.strip() else "open")

    # Ignore the result: this only clears a stale profile if one exists.
    run_command(sudo + ["nmcli", "connection", "delete", ssid], timeout=15, label="nmcli connection delete")

    add_args = ["nmcli", "connection", "add", "type", "wifi", "con-name", ssid, "ifname", WIFI_INTERFACE, "ssid", ssid]
    if password.strip():
        add_args += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password]
    rc, _, _ = run_command(sudo + add_args, timeout=30, label="nmcli connection add")
    if rc != 0:
        # nmcli echoes its arguments back on failure, so its stderr must not be logged here.
        logger.error("Failed to create the WiFi profile for %r (rc=%s)", ssid, rc)
        return f"error: could not create profile for {ssid}"

    rc, _, stderr = run_command(sudo + ["nmcli", "connection", "up", ssid], timeout=60, label="nmcli connection up")
    if rc != 0:
        logger.error("Failed to activate %r: %s", ssid, stderr or "unknown error")
        return f"error: could not connect to {ssid}"

    logger.info("Successfully configured WiFi network %r", ssid)
    return f"connected: {ssid}"
