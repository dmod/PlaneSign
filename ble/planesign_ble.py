import sys
import dbus, dbus.mainloop.glib
import subprocess
from gi.repository import GLib
from gatt import Application, Advertisement, Service, Characteristic
from gatt import find_adapter, register_app_cb, register_app_error_cb, register_ad_cb, register_ad_error_cb

BLUEZ_SERVICE_NAME =           'org.bluez'
DBUS_OM_IFACE =                'org.freedesktop.DBus.ObjectManager'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
GATT_MANAGER_IFACE =           'org.bluez.GattManager1'
GATT_CHRC_IFACE =              'org.bluez.GattCharacteristic1'
UART_SERVICE_UUID =            '6e400001-b5a3-f393-e0a9-e50e24dcca9e'
LOCAL_NAME =                   'rpi-planesign-gatt-server'
mainloop = None

class PlanesignBLEService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, UART_SERVICE_UUID, True)
        self.add_characteristic(PlanesignBLECharacteristic(bus, 0, self))
        self.add_characteristic(PlanesignTempCharacteristic(bus, 1, self))

class PlanesignBLEApplication(Application):
    def __init__(self, bus):
        Application.__init__(self, bus)
        self.add_service(PlanesignBLEService(bus, 0))

class PlanesignBLEAdvertisement(Advertisement):
    def __init__(self, bus, index):
        Advertisement.__init__(self, bus, index, 'peripheral')
        self.add_service_uuid(UART_SERVICE_UUID)
        self.add_local_name(LOCAL_NAME)
        self.include_tx_power = True

class PlanesignBLECharacteristic(Characteristic):

    TEST_CHRC_UUID = '12345678-1234-5678-1234-56789abcdef1'

    def __init__(self, bus, index, service):
        Characteristic.__init__(
                self, bus, index,
                self.TEST_CHRC_UUID,
                ['read', 'write'],
                service)
        self.value = []
        s = "Test value going out"
        for c in s:
            self.value.append(dbus.Byte(c.encode()))

    def ReadValue(self, options):
        print('TestCharacteristic Read: ' + repr(self.value))
        return self.value

    def WriteValue(self, value, options):
        print('TestCharacteristic Write: ' + repr(value))
        mystr = bytes(value).decode()
        print(mystr)
        self.value = value

class PlanesignTempCharacteristic(Characteristic):

    TEST_CHRC_UUID = '0x08CD'

    def __init__(self, bus, index, service):
        Characteristic.__init__(
                self, bus, index,
                self.TEST_CHRC_UUID,
                ['read'],
                service)

    def ReadValue(self, options):
        cmd = '/usr/bin/vcgencmd measure_temp'
        temperature = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()
        print('Temp Read: ' + temperature)

        return [dbus.Byte(x.encode()) for x in temperature]


def main():
    global mainloop
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    adapter = find_adapter(bus)
    if not adapter:
        print('BLE adapter not found')
        return

    service_manager = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, adapter), GATT_MANAGER_IFACE)
    ad_manager = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, adapter), LE_ADVERTISING_MANAGER_IFACE)

    app = PlanesignBLEApplication(bus)
    adv = PlanesignBLEAdvertisement(bus, 0)

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

if __name__ == '__main__':
    main()