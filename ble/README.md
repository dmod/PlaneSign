# PlaneSign BLE (Bluetooth Low Energy) Interface

PlaneSign exposes a BLE GATT server that allows nearby clients to monitor system health, manage Wi-Fi, control the Docker container, and trigger updates — all without needing network connectivity first.

## Advertisement

| Property | Value |
|---|---|
| **Type** | Peripheral |
| **Local Name** | `PlaneSign-BLE-XXXX` (last four hex digits of the `wlan0` MAC, uppercased) |
| **Service UUID** | `3d951a35-76c5-4207-a150-2d0cf7d2bfdd` |
| **TX Power** | Only in the fallback advertisement, if the primary one is rejected |

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

Read-only characteristics that expose basic system information. All of them are cached and
notify-capable: see [Read latency and caching](#read-latency-and-caching).

| # | Characteristic | UUID | Read | Write | Notify | Description |
|---|----------------|------|:----:|:-----:|:------:|-------------|
| 0 | CPU Temperature | `abbd155c-e9d1-4d9d-ae9e-6871b20880e4` | ✅ | — | ✅ | Raspberry Pi CPU temperature via `vcgencmd measure_temp`. Refreshed every 30 s. |
| 1 | Hostname | `7e60d076-d3fd-496c-8460-63a0454d94d9` | ✅ | — | ✅ | System hostname. |
| 2 | Uptime | `a77a6077-7302-486e-9087-853ac5899335` | ✅ | — | ✅ | Output of `/usr/bin/uptime`. Refreshed every 60 s. |
| 3 | Wi-Fi Status | `f2a3b4c5-6d7e-8f90-a1b2-c3d4e5f6a7b8` | ✅ | — | ✅ | `Connected\|SSID\|signal`, `Disconnected\|None\|0` or `Error\|…\|0`. Refreshed every 30 s and after a Wi-Fi configuration attempt. |
| 4 | IP Address | `fed6ced8-9ef1-4b7e-9f05-07963adde32b` | ✅ | — | ✅ | IPv4 address of the first connected interface (`wlan0`, `eth0`, `wlan1`, `eth1`, `usb0`), from a single `ip -4 -o addr show`. Refreshed every 60 s. |

---

### 2. Wi-Fi Management Service

**UUID:** `755f57c4-1d85-4676-9dfb-bafcacbb2915`

Allows scanning for nearby Wi-Fi networks and configuring credentials.

| # | Characteristic | UUID | Read | Write | Notify | Description |
|---|----------------|------|:----:|:-----:|:------:|-------------|
| 0 | Wi-Fi Scan | `99945678-1234-5678-1234-56789abcdef3` | ✅ | — | ✅ | Up to 10 nearby networks as `SSID\|signal\|encrypted` lines, signal in dBm. Cached for 60 s. |
| 1 | Wi-Fi Config | `99945678-1234-5678-1234-56789abcdef4` | — | ✅ | — | Write `SSID\|PASSWORD` (or `SSID\|` for open networks). The write is acknowledged immediately and the join runs in the background; watch Wi-Fi Status for the result. |

---

### 3. System Control Service

**UUID:** `312f08be-a717-40b0-9730-6d3d7c929856`

Execute a set of whitelisted system commands remotely.

| # | Characteristic | UUID | Read | Write | Notify | Description |
|---|----------------|------|:----:|:-----:|:------:|-------------|
| 0 | Safe Command | `99945678-1234-5678-1234-56789abcdef2` | ✅ | ✅ | ✅ | Write one of the allowed command keywords to execute it. The write is acknowledged immediately; the output arrives as a notification and is also returned by the next read. |
| 1 | Identify | `e64fcf70-97d7-4f4e-a5b7-8ac6004f0786` | ✅ | ✅ | ✅ | Write `identify` to make the LED matrix flash for a few seconds (via `http://127.0.0.1/api/identify`) so a user can tell which sign is which. Reads and notifications return `idle`, `ok`, or an error string. |

**Allowed commands:**

| Keyword | Command | Purpose |
|---------|---------|---------|
| `date` | `/bin/date` | Current date/time |
| `uptime` | `/usr/bin/uptime` | System uptime |
| `temp` | `/usr/bin/vcgencmd measure_temp` | CPU temperature |
| `hostname` | `/bin/hostname` | Device hostname |
| `disk` | `/bin/df -h /` | Disk usage |
| `memory` | `/usr/bin/free -h` | Memory usage |
| `reboot` | `sudo -n /usr/sbin/reboot` | Reboot the device |

---

### 4. Container Control Service

**UUID:** `a8e86355-accb-4ba4-a7c5-63206cab4b7b`

Manage the PlaneSign Docker container lifecycle, check for updates, and perform OTA updates.

| # | Characteristic | UUID | Read | Write | Notify | Description |
|---|----------------|------|:----:|:-----:|:------:|-------------|
| 0 | Container Control | `29352a73-3108-4ecc-9440-57b5a8a5c027` | ✅ | ✅ | ✅ | Read returns the live container status (name, state, running, ID), refreshed every 30 s. Write `start` or `stop` to control the `PlaneSignRuntime` container; the write is acknowledged immediately and the resulting status arrives as a notification. Stop uses `docker kill` for a forced shutdown. |
| 1 | Version | `8d1151e7-04b8-49e2-955a-daa50e1285e5` | ✅ | — | ✅ | Current PlaneSign application version from the local API (`http://127.0.0.1/api/version`), refreshed every 30 s. |
| 2 | Update Check | `a9cc9f79-aa76-4955-aeb5-85aa9299028e` | ✅ | — | ✅ | Compares the local Docker image digest against the remote GHCR digest. Checked at startup and every 15 minutes, so reads answer immediately with `up-to-date` / `update-available` plus short digest hashes, or `check failed: …`. |
| 3 | System Update | `32d1b76b-9532-44da-9a43-3b682b8be90c` | ✅ | ✅ | ✅ | Write `update` to trigger the OTA update script. Read returns current status (`idle`, `updating`, `complete`, or `failed: …`). Subscribe to notifications for real-time status changes. |
| 4 | Update Log | `f63b67f9-b823-4f8f-a528-94e286cda73e` | ✅ | — | ✅ | Streams stdout/stderr from the update script. Read returns the last 512 bytes of the log buffer (64 KB ring buffer). Subscribe to notifications for live log streaming in ≤180-byte chunks, which fit the ATT payload iOS negotiates. |

---

## Read latency and caching

BlueZ delivers every `ReadValue`/`WriteValue` on a single GLib main loop thread, and a BLE
connection only ever has one ATT transaction in flight. A handler that blocks therefore
delays every characteristic queued behind it — a four second Wi-Fi scan used to stall the
container status read that the app performs later in the same connect sequence.

The server is built around that constraint:

- `ReadValue` and `WriteValue` are declared with dbus-python's async callbacks, so a
  handler can reply later without holding the main loop. Subclasses override
  `start_read`/`start_write` (or the simpler `read_value`/`write_value`), never the D-Bus
  methods.
- Everything that shells out or talks to the network derives from `CachedValueCharacteristic`.
  Reads answer from cache immediately; the value is recomputed on a worker thread and pushed
  to subscribers. Caches are warmed at startup, on a per-characteristic interval, and again
  whenever a central connects.
- The very first read of a characteristic is held open until its initial value lands (up to
  10–15 s) rather than returning an empty string.
- Blob reads honour BlueZ's `offset` option and are served from the same cached value, so a
  value longer than the MTU no longer re-runs the underlying command once per fragment.
- Writes that trigger slow work (`start`/`stop`, `reboot`, `identify`, Wi-Fi configuration)
  are acknowledged immediately and report their outcome through notifications.
- The Wi-Fi scan reads the kernel's cached scan table and only falls back to a live `iw scan`
  when that table is nearly empty. It is deliberately *not* refreshed when a client connects:
  the Pi shares one radio between Wi-Fi and Bluetooth, so scanning degrades the very link the
  results have to travel over.

## Logging

Logs go to stdout, which systemd captures: `journalctl -u planesign-ble -f`. Set
`PLANESIGN_BLE_LOG_LEVEL=DEBUG` in the unit file to also log every subprocess timing and
cache refresh; only the `planesign` loggers follow that variable, so dbus-python's own
debug output stays out of the way.

Under systemd each line carries a syslog priority prefix that journald converts into a real
record priority, so severity filtering works:

```bash
journalctl -u planesign-ble -p warning   # slow handlers, failed commands
journalctl -u planesign-ble -p err       # handler exceptions and crashes
```

At `INFO` the service records central connect/disconnect events, every read and write with
its size and duration, and every value change. It warns whenever a handler holds the main
loop for more than 150 ms, a read takes over a second, or a subprocess fails or times out.
Exceptions — including ones escaping a worker thread, a GLib callback, or the process
itself — are logged with a full traceback at `err` or `crit` rather than being swallowed.

## Notes

- The BLE device name is derived from the last four hex digits of the `wlan0` MAC address
  (e.g. `PlaneSign-BLE-D2BC`).
- The Docker container name used for all operations is `PlaneSignRuntime`.
- The Docker image is `ghcr.io/dmod/planesign:latest`.
- Every subprocess call goes through `run_command`, which runs without a shell, always has a
  timeout, and never raises.
- Local HTTP calls use `127.0.0.1`, never `localhost`: `localhost` also resolves to `::1` and
  nginx only listens on IPv4.
- The update script is fetched from: `https://raw.githubusercontent.com/dmod/PlaneSign/main/docker_install_and_update.sh`
