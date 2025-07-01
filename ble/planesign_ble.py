import sys
import dbus, dbus.mainloop.glib
import subprocess
from gi.repository import GLib
from gatt import Application, Advertisement, Service, Characteristic
from gatt import find_adapter, set_adapter_name, register_app_cb, register_app_error_cb, register_ad_cb, register_ad_error_cb
import re
from wifi import get_wifi_status, scan_wifi, configure_wifi

BLUEZ_SERVICE_NAME =           'org.bluez'
DBUS_OM_IFACE =                'org.freedesktop.DBus.ObjectManager'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
GATT_MANAGER_IFACE =           'org.bluez.GattManager1'
GATT_CHRC_IFACE =              'org.bluez.GattCharacteristic1'
PLANESIGN_MASTER_UUID =        '3d951a35-76c5-4207-a150-2d0cf7d2bfdd'
mainloop = None

class DeviceInfoService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, '180A', True)  # Standard Device Information Service
        self.add_characteristic(PlanesignTempCharacteristic(bus, 0, self))
        self.add_characteristic(PlanesignHostnameCharacteristic(bus, 1, self))
        self.add_characteristic(PlanesignUptimeCharacteristic(bus, 2, self))
        self.add_characteristic(PlanesignWiFiStatusCharacteristic(bus, 3, self))

class SystemControlService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, '312f08be-a717-40b0-9730-6d3d7c929856', True)
        self.add_characteristic(SafeCommandCharacteristic(bus, 0, self))

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
        configure_wifi(credentials)

class PlanesignBLEApplication(Application):
    def __init__(self, bus):
        Application.__init__(self, bus)
        self.add_service(DeviceInfoService(bus, 0))
        self.add_service(WiFiManagementService(bus, 1))
        self.add_service(SystemControlService(bus, 2))

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
        temperature = subprocess.check_output('/usr/bin/vcgencmd measure_temp', shell=True).decode("utf-8").strip()
        print('Temp Read: ' + temperature)

        return [dbus.Byte(x.encode()) for x in temperature]
    
class PlanesignHostnameCharacteristic(Characteristic):
    CHRC_UUID = '7e60d076-d3fd-496c-8460-63a0454d94d9'

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.CHRC_UUID, ['read'], service)

    def ReadValue(self, options):
        hostname = subprocess.check_output('/bin/hostname', shell=True).decode("utf-8").strip()
        print('Hostname Read: ' + hostname)

        return [dbus.Byte(x.encode()) for x in hostname]
    
class PlanesignUptimeCharacteristic(Characteristic):
    CHRC_UUID = 'a77a6077-7302-486e-9087-853ac5899335'

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.CHRC_UUID, ['read'], service)

    def ReadValue(self, options):
        uptime = subprocess.check_output('/usr/bin/uptime', shell=True).decode("utf-8").strip()
        print('Uptime Read: ' + uptime)

        return [dbus.Byte(x.encode()) for x in uptime]

class PlanesignWiFiStatusCharacteristic(Characteristic):
    CHRC_UUID = 'f2a3b4c5-6d7e-8f90-a1b2-c3d4e5f6a7b8'

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.CHRC_UUID, ['read'], service)

    def ReadValue(self, options):
        wifi_status = get_wifi_status()
        print('WiFi Status Read: ' + wifi_status)
        return [dbus.Byte(x.encode()) for x in wifi_status]

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
                    shell=True
                ).decode('utf-8').strip()
                self.last_result = result
            except subprocess.CalledProcessError as e:
                self.last_result = f"Error executing command: {str(e)}"
        else:
            self.last_result = f"Command '{command}' not in allowed list"

class WiFiScanCharacteristic(Characteristic):
    WIFI_SCAN_CHRC_UUID = '99945678-1234-5678-1234-56789abcdef3'

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.WIFI_SCAN_CHRC_UUID, ['read'], service)
        self.scan_result = scan_wifi()

    def ReadValue(self, options):
        print('WiFiScanCharacteristic Read requested - auto-scanning...')
        # Auto-trigger scan on read
        print(f'Scan result size: {len(self.scan_result)}')
        return [dbus.Byte(x.encode()) for x in self.scan_result]

def main():
    global mainloop
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    adapter = find_adapter(bus)
    if not adapter:
        print('BLE adapter not found')
        return
    
    # Set device name consistently
    device_name = f"PlaneSign-BLE-{get_mac_suffix()}"
    
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

def get_mac_suffix(interface='wlan0'):
    cmd = f"cat /sys/class/net/{interface}/address"
    mac_address = subprocess.check_output(cmd, shell=True).decode().strip()
    return mac_address.replace(":", "")[-4:].upper()

if __name__ == '__main__':
    main()