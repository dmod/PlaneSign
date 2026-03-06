# PlaneSign BLE (Bluetooth Low Energy) Interface

PlaneSign exposes a BLE GATT server that allows nearby clients to monitor system health, manage Wi-Fi, control the Docker container, and trigger updates — all without needing network connectivity first.

## Advertisement

| Property | Value |
|---|---|
| **Type** | Peripheral |
| **Local Name** | `PlaneSign-BLE-XXXXXXXXXXXX` (full `wlan0` MAC, colons stripped, uppercased) |
| **Service UUID** | `3d951a35-76c5-4207-a150-2d0cf7d2bfdd` |
| **TX Power** | Included |

---

## Application — `PlanesignBLEApplication`

The application registers **4 GATT services** on the D-Bus system bus:

| # | Service | UUID |
|---|---------|------|
| 0 | Basic Info | `19f65cb7-deba-40cc-a00f-6eaa29b6ea85` |
| 1 | Wi-Fi Management | `755f57c4-1d85-4676-9dfb-bafcacbb2915` |
| 2 | System Control | `312f08be-a717-40b0-9730-6d3d7c929856` |
| 3 | Container Control | `a8e86355-accb-4ba4-a7c5-63206cab4b7b` |

---

## Service Details & Characteristics

### 1. Basic Info Service

**UUID:** `19f65cb7-deba-40cc-a00f-6eaa29b6ea85`

Read-only characteristics that expose basic system information.

| # | Characteristic | UUID | Read | Write | Notify | Description |
|---|----------------|------|:----:|:-----:|:------:|-------------|
| 0 | CPU Temperature | `abbd155c-e9d1-4d9d-ae9e-6871b20880e4` | ✅ | — | — | Returns the Raspberry Pi CPU temperature via `vcgencmd measure_temp`. |
| 1 | Hostname | `7e60d076-d3fd-496c-8460-63a0454d94d9` | ✅ | — | — | Returns the system hostname. |
| 2 | Uptime | `a77a6077-7302-486e-9087-853ac5899335` | ✅ | — | — | Returns system uptime output from `/usr/bin/uptime`. |
| 3 | Wi-Fi Status | `f2a3b4c5-6d7e-8f90-a1b2-c3d4e5f6a7b8` | ✅ | — | — | Returns the current Wi-Fi connection status (SSID, signal, etc.). |
| 4 | IP Address | `fed6ced8-9ef1-4b7e-9f05-07963adde32b` | ✅ | — | — | Returns the IPv4 address of the first connected interface (`wlan0`, `eth0`, `wlan1`, `eth1`, `usb0`). |

---

### 2. Wi-Fi Management Service

**UUID:** `755f57c4-1d85-4676-9dfb-bafcacbb2915`

Allows scanning for nearby Wi-Fi networks and configuring credentials.

| # | Characteristic | UUID | Read | Write | Notify | Description |
|---|----------------|------|:----:|:-----:|:------:|-------------|
| 0 | Wi-Fi Scan | `99945678-1234-5678-1234-56789abcdef3` | ✅ | — | — | Returns a list of available Wi-Fi networks discovered during a scan. |
| 1 | Wi-Fi Config | `99945678-1234-5678-1234-56789abcdef4` | — | ✅ | — | Write Wi-Fi credentials (SSID + password) to configure and connect to a network. |

---

### 3. System Control Service

**UUID:** `312f08be-a717-40b0-9730-6d3d7c929856`

Execute a set of whitelisted system commands remotely.

| # | Characteristic | UUID | Read | Write | Notify | Description |
|---|----------------|------|:----:|:-----:|:------:|-------------|
| 0 | Safe Command | `99945678-1234-5678-1234-56789abcdef2` | ✅ | ✅ | — | Write one of the allowed command keywords to execute it; read to get the result. |

**Allowed commands:**

| Keyword | Command | Purpose |
|---------|---------|---------|
| `date` | `/bin/date` | Current date/time |
| `uptime` | `/usr/bin/uptime` | System uptime |
| `temp` | `/usr/bin/vcgencmd measure_temp` | CPU temperature |
| `hostname` | `/bin/hostname` | Device hostname |
| `disk` | `/bin/df -h /` | Disk usage |
| `memory` | `/usr/bin/free -h` | Memory usage |
| `reboot` | `sudo /usr/sbin/reboot` | Reboot the device |

---

### 4. Container Control Service

**UUID:** `a8e86355-accb-4ba4-a7c5-63206cab4b7b`

Manage the PlaneSign Docker container lifecycle, check for updates, and perform OTA updates.

| # | Characteristic | UUID | Read | Write | Notify | Description |
|---|----------------|------|:----:|:-----:|:------:|-------------|
| 0 | Container Control | `29352a73-3108-4ecc-9440-57b5a8a5c027` | ✅ | ✅ | — | Read returns the live container status (name, state, running, ID). Write `start` or `stop` to control the `PlaneSignRuntime` container. Stop uses `docker kill` for a forced shutdown. |
| 1 | Version | `8d1151e7-04b8-49e2-955a-daa50e1285e5` | ✅ | — | — | Fetches the current PlaneSign application version from the local API (`http://localhost/api/version`). |
| 2 | Update Check | `a9cc9f79-aa76-4955-aeb5-85aa9299028e` | ✅ | — | — | Compares the local Docker image digest against the remote GHCR digest. Returns `up-to-date` or `update-available` with short digest hashes. |
| 3 | System Update | `32d1b76b-9532-44da-9a43-3b682b8be90c` | ✅ | ✅ | ✅ | Write `update` to trigger the OTA update script. Read returns current status (`idle`, `updating`, `complete`, or `failed: …`). Subscribe to notifications for real-time status changes. |
| 4 | Update Log | `f63b67f9-b823-4f8f-a528-94e286cda73e` | ✅ | — | ✅ | Streams stdout/stderr from the update script. Read returns the last 512 bytes of the log buffer (64 KB ring buffer). Subscribe to notifications for live log streaming in ≤480-byte BLE-safe chunks. |

---

## Notes

- The BLE device name is derived from the full `wlan0` MAC address with colons stripped (e.g., `PlaneSign-BLE-AABBCCDDEEFF`).
- The Docker container name used for all operations is `PlaneSignRuntime`.
- The Docker image is `ghcr.io/dmod/planesign:latest`.
- All subprocess calls use timeouts (typically 5–8 seconds) to prevent BLE operations from hanging.
- The update script is fetched from: `https://raw.githubusercontent.com/dmod/PlaneSign/main/docker_install_and_update.sh`
