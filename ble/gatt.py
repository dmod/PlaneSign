import logging
import os
import subprocess
import sys
import threading
import time

import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

logger = logging.getLogger("planesign.ble")

mainloop = None

BLUEZ_SERVICE_NAME = "org.bluez"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"

GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
GATT_DESC_IFACE = "org.bluez.GattDescriptor1"

LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"
ADAPTER_IFACE = "org.bluez.Adapter1"

# BlueZ delivers every GATT method call on the thread running the GLib main loop, and
# dbus-python replies must be sent from that same thread.
_MAIN_THREAD_ID = threading.get_ident()


def configure_logging(level=None):
    """Log to stdout with timestamps so `journalctl -u planesign-ble` is readable."""
    level = (level or os.environ.get("PLANESIGN_BLE_LOG_LEVEL", "INFO")).upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, level, logging.INFO))
    return logger


def set_mainloop(loop):
    """Register the loop so a failed registration can end the process.

    Previously this module's `mainloop` was never assigned, so the error callbacks below
    quit nothing: a failed GATT or advertisement registration left the process running
    with no services and systemd never restarted it.
    """
    global mainloop
    mainloop = loop


def run_on_main_loop(func, *args):
    """Invoke func on the GLib main loop thread, directly if already there."""
    if threading.get_ident() == _MAIN_THREAD_ID:
        func(*args)
        return

    def invoke():
        func(*args)
        return False

    GLib.idle_add(invoke)


def encode_ble_value(value, offset=0):
    """Encode a characteristic value as a GATT byte array starting at `offset`.

    Encodes the whole string to UTF-8 first: `dbus.Byte(char.encode())` raises on any
    character that is not a single byte, which turns a read into an ATT error. The offset
    is set by BlueZ for the blob reads a client issues when a value is longer than the
    negotiated MTU.
    """
    if value is None:
        data = b""
    elif isinstance(value, (bytes, bytearray)):
        data = bytes(value)
    else:
        data = str(value).encode("utf-8", errors="replace")
    if offset:
        data = data[offset:]
    return dbus.Array([dbus.Byte(b) for b in data], signature="y")


def read_option_int(options, key, default=0):
    try:
        return int(options.get(key, default))
    except (TypeError, ValueError, AttributeError):
        return default


def describe_options(options):
    """Compact summary of BlueZ's read/write options for log lines."""
    if not options:
        return "no options"
    parts = []
    device = options.get("device")
    if device:
        parts.append(f"device={str(device).rsplit('/', 1)[-1]}")
    for key in ("offset", "mtu", "type", "link"):
        if key in options:
            parts.append(f"{key}={options[key]}")
    return " ".join(parts) or "no options"


def to_dbus_error(exc):
    if isinstance(exc, dbus.exceptions.DBusException):
        return exc
    return FailedException(str(exc) or type(exc).__name__)


def run_command(args, timeout, label=None):
    """Run a command without a shell and never raise.

    Returns (returncode, stdout, stderr), where -1 means the command could not be executed
    at all and -2 means it timed out. Every call is timed so slow helpers show up in the
    service log instead of silently delaying GATT traffic.
    """
    label = label or args[0]
    started = time.monotonic()
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        logger.error("%s timed out after %.0fs", label, timeout)
        return -2, "", f"timed out after {timeout:.0f}s"
    except FileNotFoundError:
        logger.error("%s is not installed (%s)", label, args[0])
        return -1, "", f"{args[0]} not found"
    except Exception as exc:
        logger.exception("%s could not be executed", label)
        return -1, "", str(exc)

    elapsed_ms = (time.monotonic() - started) * 1000
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0:
        logger.warning("%s exited %d in %.0f ms: %s", label, completed.returncode, elapsed_ms, stderr or stdout or "no output")
    elif elapsed_ms >= 1000:
        logger.warning("%s took %.0f ms", label, elapsed_ms)
    else:
        logger.debug("%s finished in %.0f ms (%d bytes)", label, elapsed_ms, len(stdout))
    return completed.returncode, stdout, stderr


class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.freedesktop.DBus.Error.InvalidArgs"


class NotSupportedException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.NotSupported"


class NotPermittedException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.NotPermitted"


class InvalidValueLengthException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.InvalidValueLength"


class FailedException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.Failed"


class Advertisement(dbus.service.Object):
    PATH_BASE = "/org/bluez/example/advertisement"

    def __init__(self, bus, index, advertising_type):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = advertising_type
        self.service_uuids = None
        self.manufacturer_data = None
        self.solicit_uuids = None
        self.service_data = None
        self.local_name = None
        self.include_tx_power = None
        self.data = None
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        properties = dict()
        properties["Type"] = self.ad_type
        if self.service_uuids is not None:
            properties["ServiceUUIDs"] = dbus.Array(self.service_uuids, signature="s")
        if self.solicit_uuids is not None:
            properties["SolicitUUIDs"] = dbus.Array(self.solicit_uuids, signature="s")
        if self.manufacturer_data is not None:
            properties["ManufacturerData"] = dbus.Dictionary(self.manufacturer_data, signature="qv")
        if self.service_data is not None:
            properties["ServiceData"] = dbus.Dictionary(self.service_data, signature="sv")
        if self.local_name is not None:
            properties["LocalName"] = dbus.String(self.local_name)
        if self.include_tx_power:
            properties["IncludeTxPower"] = dbus.Boolean(self.include_tx_power)

        if self.data is not None:
            properties["Data"] = dbus.Dictionary(self.data, signature="yv")
        return {LE_ADVERTISEMENT_IFACE: properties}

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service_uuid(self, uuid):
        if not self.service_uuids:
            self.service_uuids = []
        self.service_uuids.append(uuid)

    def add_solicit_uuid(self, uuid):
        if not self.solicit_uuids:
            self.solicit_uuids = []
        self.solicit_uuids.append(uuid)

    def add_manufacturer_data(self, manuf_code, data):
        if not self.manufacturer_data:
            self.manufacturer_data = dbus.Dictionary({}, signature="qv")
        self.manufacturer_data[manuf_code] = dbus.Array(data, signature="y")

    def add_service_data(self, uuid, data):
        if not self.service_data:
            self.service_data = dbus.Dictionary({}, signature="sv")
        self.service_data[uuid] = dbus.Array(data, signature="y")

    def add_local_name(self, name):
        if not self.local_name:
            self.local_name = ""
        self.local_name = dbus.String(name)

    def add_data(self, ad_type, data):
        if not self.data:
            self.data = dbus.Dictionary({}, signature="yv")
        self.data[ad_type] = dbus.Array(data, signature="y")

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != LE_ADVERTISEMENT_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[LE_ADVERTISEMENT_IFACE]

    @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature="", out_signature="")
    def Release(self):
        logger.info("Advertisement %s released by BlueZ", self.path)


def register_ad_cb():
    logger.info("Advertisement registered")


def _quit_mainloop():
    if mainloop is not None:
        mainloop.quit()
    else:
        logger.error("No main loop registered; cannot shut down cleanly")


def register_ad_error_cb(error):
    logger.error("Failed to register advertisement: %s", error)
    _quit_mainloop()


def find_adapter(bus):
    remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, "/"), DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()
    for o, props in objects.items():
        if LE_ADVERTISING_MANAGER_IFACE in props and GATT_MANAGER_IFACE in props:
            logger.info("Selecting Bluetooth adapter %s", o)
            return o
        logger.debug("Skipping object %s (not an LE GATT adapter)", o)
    return None


def find_adapter_wait(bus, timeout_seconds=15, interval=0.5):
    deadline = time.monotonic() + timeout_seconds
    attempts = 0
    while time.monotonic() < deadline:
        attempts += 1
        try:
            adapter = find_adapter(bus)
        except dbus.exceptions.DBusException as exc:
            logger.warning("Adapter lookup failed (attempt %d): %s", attempts, exc)
            adapter = None
        if adapter:
            return adapter
        time.sleep(interval)
    logger.error("No LE adapter found after %ds (%d attempts)", timeout_seconds, attempts)
    return None


def set_adapter_name(bus, adapter, name):
    adapter_props = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, adapter), DBUS_PROP_IFACE)
    adapter_props.Set(ADAPTER_IFACE, "Alias", name)
    logger.info("Adapter alias set to %s", name)


def ensure_adapter_ready(bus, adapter, timeout_seconds=15):
    adapter_props = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, adapter), DBUS_PROP_IFACE)
    try:
        adapter_props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(True))
    except Exception as exc:
        logger.warning("Unable to enable Bluetooth adapter: %s", exc)

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            powered = adapter_props.Get(ADAPTER_IFACE, "Powered")
            if powered:
                return True
        except Exception as exc:
            logger.warning("Adapter readiness probe failed: %s", exc)
        time.sleep(0.5)
    return False


def register_app_cb():
    logger.info("GATT application registered")


def register_app_error_cb(error):
    logger.error("Failed to register GATT application: %s", error)
    _quit_mainloop()


class Service(dbus.service.Object):
    PATH_BASE = "/org/bluez/example/service"

    def __init__(self, bus, index, uuid, primary):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {GATT_SERVICE_IFACE: {"UUID": self.uuid, "Primary": self.primary, "Characteristics": dbus.Array(self.get_characteristic_paths(), signature="o")}}

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

    def get_characteristic_paths(self):
        result = []
        for chrc in self.characteristics:
            result.append(chrc.get_path())
        return result

    def get_characteristics(self):
        return self.characteristics

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != GATT_SERVICE_IFACE:
            raise InvalidArgsException()

        return self.get_properties()[GATT_SERVICE_IFACE]


class Characteristic(dbus.service.Object):
    """Base GATT characteristic that answers BlueZ asynchronously.

    BlueZ delivers every ReadValue/WriteValue on the single GLib main loop thread, and a
    connection only ever has one ATT transaction in flight. A handler that blocks for a
    second therefore delays every characteristic queued behind it, which is what made
    later reads (container status in particular) arrive late or not at all. These methods
    use dbus-python's async callbacks so a subclass can reply later from a worker thread;
    subclasses override `start_read`/`start_write` (or the simpler `read_value`/
    `write_value`) instead of the D-Bus methods themselves.
    """

    # Anything holding the main loop longer than this starves other GATT operations.
    SLOW_HANDLER_SECONDS = 0.15

    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + "/char" + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.descriptors = []
        self.name = type(self).__name__
        self.notifying = False
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {GATT_CHRC_IFACE: {"Service": self.service.get_path(), "UUID": self.uuid, "Flags": self.flags, "Descriptors": dbus.Array(self.get_descriptor_paths(), signature="o")}}

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_descriptor(self, descriptor):
        self.descriptors.append(descriptor)

    def get_descriptor_paths(self):
        result = []
        for desc in self.descriptors:
            result.append(desc.get_path())
        return result

    def get_descriptors(self):
        return self.descriptors

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != GATT_CHRC_IFACE:
            raise InvalidArgsException()

        return self.get_properties()[GATT_CHRC_IFACE]

    # --- Subclass hooks -------------------------------------------------

    def read_value(self, options):
        """Return the value for a read. Runs on the main loop thread, so it must be fast."""
        raise NotSupportedException()

    def start_read(self, options, respond, fail):
        """Begin a read; call respond(value) or fail(exception), possibly from a thread."""
        respond(self.read_value(options))

    def write_value(self, value, options):
        """Handle a write. Runs on the main loop thread, so it must be fast."""
        raise NotPermittedException()

    def start_write(self, value, options, done, fail):
        """Begin a write; call done() or fail(exception), possibly from a thread."""
        self.write_value(value, options)
        done()

    def on_start_notify(self):
        pass

    def on_stop_notify(self):
        pass

    # --- D-Bus surface --------------------------------------------------

    @dbus.service.method(GATT_CHRC_IFACE, in_signature="a{sv}", out_signature="ay", async_callbacks=("_dbus_reply", "_dbus_error"))
    def ReadValue(self, options, _dbus_reply, _dbus_error):
        started = time.monotonic()
        offset = read_option_int(options, "offset")
        logger.debug("%s ReadValue (%s)", self.name, describe_options(options))
        state = {"answered": False, "reply": _dbus_reply, "error": _dbus_error}

        def respond(value):
            run_on_main_loop(self._finish_read, state, started, offset, value)

        def fail(exc):
            run_on_main_loop(self._finish_read_error, state, started, exc)

        try:
            self.start_read(options, respond, fail)
        except Exception as exc:
            logger.exception("%s start_read raised", self.name)
            fail(exc)

        self._warn_if_slow("ReadValue", started)

    def _finish_read(self, state, started, offset, value):
        if state["answered"]:
            logger.warning("%s answered the same read twice; ignoring the duplicate", self.name)
            return
        state["answered"] = True
        try:
            payload = encode_ble_value(value, offset)
        except Exception as exc:
            logger.exception("%s could not encode its value", self.name)
            state["error"](to_dbus_error(exc))
            return
        elapsed_ms = (time.monotonic() - started) * 1000
        log = logger.warning if elapsed_ms >= 1000 else logger.info
        log("%s read answered: %d bytes at offset %d in %.0f ms", self.name, len(payload), offset, elapsed_ms)
        state["reply"](payload)

    def _finish_read_error(self, state, started, exc):
        if state["answered"]:
            return
        state["answered"] = True
        logger.error("%s read failed after %.0f ms: %s", self.name, (time.monotonic() - started) * 1000, exc)
        state["error"](to_dbus_error(exc))

    @dbus.service.method(GATT_CHRC_IFACE, in_signature="aya{sv}", async_callbacks=("_dbus_reply", "_dbus_error"))
    def WriteValue(self, value, options, _dbus_reply, _dbus_error):
        started = time.monotonic()
        payload = bytes(value)
        logger.info("%s WriteValue: %d bytes (%s)", self.name, len(payload), describe_options(options))
        state = {"answered": False, "reply": _dbus_reply, "error": _dbus_error}

        def done():
            run_on_main_loop(self._finish_write, state, started)

        def fail(exc):
            run_on_main_loop(self._finish_write_error, state, started, exc)

        try:
            self.start_write(payload, options, done, fail)
        except Exception as exc:
            logger.exception("%s start_write raised", self.name)
            fail(exc)

        self._warn_if_slow("WriteValue", started)

    def _finish_write(self, state, started):
        if state["answered"]:
            return
        state["answered"] = True
        logger.info("%s write accepted in %.0f ms", self.name, (time.monotonic() - started) * 1000)
        state["reply"]()

    def _finish_write_error(self, state, started, exc):
        if state["answered"]:
            return
        state["answered"] = True
        logger.error("%s write failed after %.0f ms: %s", self.name, (time.monotonic() - started) * 1000, exc)
        state["error"](to_dbus_error(exc))

    def _warn_if_slow(self, operation, started):
        blocked_ms = (time.monotonic() - started) * 1000
        if blocked_ms > self.SLOW_HANDLER_SECONDS * 1000:
            logger.warning("%s %s held the BLE main loop for %.0f ms; every other GATT operation was queued behind it", self.name, operation, blocked_ms)

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        if self.notifying:
            logger.debug("%s StartNotify: already notifying", self.name)
            return
        self.notifying = True
        logger.info("%s notifications enabled", self.name)
        try:
            self.on_start_notify()
        except Exception:
            logger.exception("%s on_start_notify raised", self.name)

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        self.notifying = False
        logger.info("%s notifications disabled", self.name)
        try:
            self.on_stop_notify()
        except Exception:
            logger.exception("%s on_stop_notify raised", self.name)

    def notify_value(self, value):
        """Push a value to subscribers. Must run on the main loop thread."""
        if not self.notifying:
            return
        try:
            payload = encode_ble_value(value)
            self.PropertiesChanged(GATT_CHRC_IFACE, {"Value": payload}, [])
            logger.debug("%s notified %d bytes", self.name, len(payload))
        except Exception:
            logger.exception("%s could not emit a notification", self.name)

    @dbus.service.signal(DBUS_PROP_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class Descriptor(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, characteristic):
        self.path = characteristic.path + "/desc" + str(index)
        self.bus = bus
        self.uuid = uuid
        self.flags = flags
        self.chrc = characteristic
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {GATT_DESC_IFACE: {"Characteristic": self.chrc.get_path(), "UUID": self.uuid, "Flags": self.flags}}

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != GATT_DESC_IFACE:
            raise InvalidArgsException()

        return self.get_properties()[GATT_DESC_IFACE]

    @dbus.service.method(GATT_DESC_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        logger.warning("Descriptor %s has no ReadValue implementation", self.path)
        raise NotSupportedException()

    @dbus.service.method(GATT_DESC_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value, options):
        logger.warning("Descriptor %s has no WriteValue implementation", self.path)
        raise NotSupportedException()


class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = "/"
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    def get_characteristics(self):
        for service in self.services:
            for chrc in service.get_characteristics():
                yield chrc

    @dbus.service.method(DBUS_OM_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        response = {}

        for service in self.services:
            response[service.get_path()] = service.get_properties()
            chrcs = service.get_characteristics()
            for chrc in chrcs:
                response[chrc.get_path()] = chrc.get_properties()
                descs = chrc.get_descriptors()
                for desc in descs:
                    response[desc.get_path()] = desc.get_properties()

        logger.info("BlueZ requested the object tree: %d services, %d objects", len(self.services), len(response))
        return response
