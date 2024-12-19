import sys
import dbus, dbus.mainloop.glib
import subprocess
from gi.repository import GLib
from gatt import Application, Advertisement, Service, Characteristic
from gatt import find_adapter, register_app_cb, register_app_error_cb, register_ad_cb, register_ad_error_cb
import re

BLUEZ_SERVICE_NAME =           'org.bluez'
DBUS_OM_IFACE =                'org.freedesktop.DBus.ObjectManager'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
GATT_MANAGER_IFACE =           'org.bluez.GattManager1'
GATT_CHRC_IFACE =              'org.bluez.GattCharacteristic1'
UART_SERVICE_UUID =            '997fbca2-ffa1-4828-9952-0faa398c5fb3'
LOCAL_NAME =                   'rpi-planesign-gatt-server'
COMMAND_SERVICE_UUID = '997fbca2-ffa1-4828-9953-0faa398c5fb3'
WIFI_SCAN_SERVICE_UUID = '997fbca2-ffa1-4828-9954-0faa398c5fb3'
mainloop = None

class PlanesignBLEService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, UART_SERVICE_UUID, True)
        self.add_characteristic(PlanesignBLECharacteristic(bus, 0, self))
        self.add_characteristic(PlanesignTempCharacteristic(bus, 1, self))

class CommandExecutionService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, COMMAND_SERVICE_UUID, True)
        self.add_characteristic(CommandCharacteristic(bus, 0, self))

class WiFiScanService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, WIFI_SCAN_SERVICE_UUID, True)
        self.add_characteristic(WiFiScanCharacteristic(bus, 0, self))

class PlanesignBLEApplication(Application):
    def __init__(self, bus):
        Application.__init__(self, bus)
        self.add_service(PlanesignBLEService(bus, 0))
        self.add_service(CommandExecutionService(bus, 1))
        self.add_service(WiFiScanService(bus, 2))

class PlanesignBLEAdvertisement(Advertisement):
    def __init__(self, bus, index):
        Advertisement.__init__(self, bus, index, 'peripheral')
        self.add_service_uuid(UART_SERVICE_UUID)
        self.add_local_name(LOCAL_NAME)
        self.include_tx_power = True

class PlanesignBLECharacteristic(Characteristic):

    TEST_CHRC_UUID = '99945678-1234-5678-1234-56789abcdef1'

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
        return self.value

    def WriteValue(self, value, options):
        print('TestCharacteristic Write: ' + repr(value))
        mystr = bytes(value).decode()
        print(mystr)
        self.value = value

class PlanesignTempCharacteristic(Characteristic):

    # name: Temperature Measurement
    # id: org.bluetooth.characteristic.temperature_measurement
    CHRC_UUID = '00002a1c-0000-1000-8000-00805f9b34fb'

    def __init__(self, bus, index, service):
        Characteristic.__init__(
                self, bus, index,
                self.CHRC_UUID,
                ['read'],
                service)

    def ReadValue(self, options):
        cmd = '/usr/bin/vcgencmd measure_temp'
        temperature = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()
        print('Temp Read: ' + temperature)

        return [dbus.Byte(x.encode()) for x in temperature]

class CommandCharacteristic(Characteristic):
    COMMAND_CHRC_UUID = '99945678-1234-5678-1234-56789abcdef2'

    # List of allowed commands
    ALLOWED_COMMANDS = {
        'date': '/bin/date',
        'uptime': '/usr/bin/uptime',
        'temp': '/usr/bin/vcgencmd measure_temp',
        'hostname': '/bin/hostname',
        'reboot': 'sudo /usr/sbin/reboot',
    }

    def __init__(self, bus, index, service):
        Characteristic.__init__(
            self, bus, index,
            self.COMMAND_CHRC_UUID,
            ['read', 'write'],
            service)
        self.value = []
        self.last_result = "No command executed yet"

    def ReadValue(self, options):
        print('CommandCharacteristic Read: ' + self.last_result)
        return [dbus.Byte(x.encode()) for x in self.last_result]

    def WriteValue(self, value, options):
        command = bytes(value).decode().strip()
        print('CommandCharacteristic Write: ' + command)

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
        Characteristic.__init__(
            self, bus, index,
            self.WIFI_SCAN_CHRC_UUID,
            ['read', 'write'],
            service)
        self.value = []
        self.last_scan = "Waiting..."

    def scan_wifi(self):
        try:
            print("Scanning WiFi...")
            subprocess.run(['sudo', 'iwlist', 'wlan0', 'scan'], capture_output=True)
            # Get scan results
            cmd_output = subprocess.check_output(['sudo', 'iwlist', 'wlan0', 'scan'], 
                                              stderr=subprocess.STDOUT).decode('utf-8')
            
            # Parse the output to get networks
            networks = []
            for cell in cmd_output.split('Cell ')[1:]:
                ssid_match = re.search(r'ESSID:"([^"]*)"', cell)
                signal_match = re.search(r'Quality=(\d+/\d+).*Signal level=([-\d]+) dBm', cell)
                encryption_match = re.search(r'Encryption key:(\w+)', cell)
                
                if ssid_match and signal_match and encryption_match:
                    ssid = ssid_match.group(1)
                    quality = signal_match.group(1)
                    signal = signal_match.group(2)
                    encrypted = encryption_match.group(1)
                    print(f"Found: {ssid} | Sig: {signal}dBm | Qual: {quality} | Enc: {encrypted}")
                    networks.append(f"{ssid} | Sig: {signal}dBm | Qual: {quality} | Enc: {encrypted}")
            
            print(f"Found {len(networks)} networks")
            self.last_scan = "\n".join(networks)[:30] if networks else "No networks found"
        except subprocess.CalledProcessError as e:
            self.last_scan = f"Error scanning WiFi: {str(e)}"
        except Exception as e:
            self.last_scan = f"Unexpected error: {str(e)}"

    def ReadValue(self, options):
        print('WiFiScanCharacteristic Read requested')
        return [dbus.Byte(x.encode()) for x in self.last_scan]

    def WriteValue(self, value, options):
        command = bytes(value).decode().strip()
        print('WifiCharacteristic Write: ' + command)

        if command == "scan":
            self.scan_wifi()  # Perform a new scan on each read
        else:
            self.last_scan = f"Command '{command}' not scan"

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