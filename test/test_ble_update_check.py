import importlib.util
import pathlib
import sys
import types
import unittest
from unittest import mock


class FakeCharacteristic:
    def __init__(self, bus, index, uuid, flags, service):
        self.flags = flags
        self.notifications = []

    def PropertiesChanged(self, interface, changed, invalidated):
        self.notifications.append((interface, changed, invalidated))


class DeferredThread:
    instances = []

    def __init__(self, target, name, daemon):
        self.target = target
        self.name = name
        self.daemon = daemon
        self.started = False
        self.instances.append(self)

    def start(self):
        self.started = True


def load_planesign_ble():
    dbus = types.ModuleType("dbus")
    dbus.Byte = lambda value: value
    dbus.Array = lambda values, signature=None: list(values)
    dbus_mainloop = types.ModuleType("dbus.mainloop")
    dbus_mainloop_glib = types.ModuleType("dbus.mainloop.glib")
    dbus.mainloop = dbus_mainloop
    dbus_mainloop.glib = dbus_mainloop_glib

    glib = types.SimpleNamespace(idle_add=lambda callback, *args: callback(*args))
    gi = types.ModuleType("gi")
    gi_repository = types.ModuleType("gi.repository")
    gi.repository = gi_repository
    gi_repository.GLib = glib

    gatt = types.ModuleType("gatt")
    gatt.Application = type("Application", (), {})
    gatt.Advertisement = type("Advertisement", (), {})
    gatt.Service = type("Service", (), {})
    gatt.Characteristic = FakeCharacteristic
    gatt.find_adapter_wait = lambda *args, **kwargs: None
    gatt.set_adapter_name = lambda *args, **kwargs: None
    gatt.register_app_cb = lambda *args, **kwargs: None
    gatt.register_app_error_cb = lambda *args, **kwargs: None
    gatt.register_ad_cb = lambda *args, **kwargs: None
    gatt.register_ad_error_cb = lambda *args, **kwargs: None

    wifi = types.ModuleType("wifi")
    wifi.get_current_wifi_status = lambda: ""
    wifi.scan_wifi = lambda: ""
    wifi.configure_wifi = lambda credentials: None

    stubs = {
        "dbus": dbus,
        "dbus.mainloop": dbus_mainloop,
        "dbus.mainloop.glib": dbus_mainloop_glib,
        "gi": gi,
        "gi.repository": gi_repository,
        "gatt": gatt,
        "wifi": wifi,
    }
    with mock.patch.dict(sys.modules, stubs):
        module_path = pathlib.Path(__file__).parents[1] / "ble" / "planesign_ble.py"
        spec = importlib.util.spec_from_file_location("planesign_ble_under_test", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


planesign_ble = load_planesign_ble()


class DockerUpdateCheckCharacteristicTest(unittest.TestCase):
    def setUp(self):
        DeferredThread.instances.clear()
        self.characteristic = planesign_ble.DockerUpdateCheckCharacteristic(None, 0, None)

    @staticmethod
    def decode_value(value):
        return b"".join(value).decode("utf-8")

    def test_first_read_returns_immediately_and_notifies_on_completion(self):
        self.characteristic._check_for_update = mock.Mock(return_value="up-to-date|local=abc|remote=abc")

        with mock.patch.object(planesign_ble.threading, "Thread", DeferredThread), mock.patch.object(planesign_ble.time, "monotonic", return_value=100):
            self.characteristic.StartNotify()
            value = self.characteristic.ReadValue({})
            self.assertEqual("checking", self.decode_value(value))
            self.assertEqual(1, len(DeferredThread.instances))
            self.assertTrue(DeferredThread.instances[0].started)

            DeferredThread.instances[0].target()

            self.assertEqual(1, len(self.characteristic.notifications))
            notification = self.characteristic.notifications[0][1]["Value"]
            self.assertEqual("up-to-date|local=abc|remote=abc", bytes(notification).decode("utf-8"))
            self.assertEqual("up-to-date|local=abc|remote=abc", self.decode_value(self.characteristic.ReadValue({})))
            self.assertEqual(1, len(DeferredThread.instances))

    def test_one_shot_read_preserves_synchronous_result(self):
        self.characteristic._check_for_update = mock.Mock(return_value="update-available|local=abc|remote=def")

        with mock.patch.object(planesign_ble.threading, "Thread", DeferredThread), mock.patch.object(planesign_ble.time, "monotonic", return_value=100):
            value = self.characteristic.ReadValue({})

        self.assertEqual("update-available|local=abc|remote=def", self.decode_value(value))
        self.assertEqual(0, len(DeferredThread.instances))

    def test_repeated_reads_do_not_overlap_checks(self):
        with mock.patch.object(planesign_ble.threading, "Thread", DeferredThread), mock.patch.object(planesign_ble.time, "monotonic", return_value=100):
            self.characteristic.StartNotify()
            self.characteristic.ReadValue({})
            self.characteristic.ReadValue({})

        self.assertEqual(1, len(DeferredThread.instances))

    def test_stale_cache_is_returned_while_refresh_starts(self):
        self.characteristic._cached_result = "up-to-date|local=abc|remote=abc"
        self.characteristic._last_checked_at = 100

        with mock.patch.object(planesign_ble.threading, "Thread", DeferredThread), mock.patch.object(planesign_ble.time, "monotonic", return_value=401):
            self.characteristic.StartNotify()
            value = self.characteristic.ReadValue({})

        self.assertEqual("up-to-date|local=abc|remote=abc", self.decode_value(value))
        self.assertEqual(1, len(DeferredThread.instances))

    def test_failed_check_uses_shorter_cache_ttl(self):
        self.characteristic._cached_result = "check failed: could not get remote digest"
        self.characteristic._last_checked_at = 100

        with mock.patch.object(planesign_ble.threading, "Thread", DeferredThread), mock.patch.object(planesign_ble.time, "monotonic", return_value=131):
            self.characteristic.StartNotify()

        self.assertEqual(1, len(DeferredThread.instances))


if __name__ == "__main__":
    unittest.main()