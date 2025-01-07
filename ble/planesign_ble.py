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
PLANESIGN_MASTER_UUID =        '3d951a35-76c5-4207-a150-2d0cf7d2bfdd'
mainloop = None

class PlanesignBLEInfoService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, '97164323-9362-4883-a30d-45b2f400fd3c', True)
        self.add_characteristic(PlanesignTempCharacteristic(bus, 0, self))
        self.add_characteristic(PlanesignHostnameCharacteristic(bus, 1, self))
        self.add_characteristic(PlanesignUptimeCharacteristic(bus, 2, self))

class CommandExecutionService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, '312f08be-a717-40b0-9730-6d3d7c929856', True)
        self.add_characteristic(CommandCharacteristic(bus, 0, self))

class WiFiScanService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, '755f57c4-1d85-4676-9dfb-bafcacbb2915', True)
        self.add_characteristic(WiFiScanCharacteristic(bus, 0, self))

class PlanesignBLEApplication(Application):
    def __init__(self, bus):
        Application.__init__(self, bus)
        self.add_service(PlanesignBLEInfoService(bus, 0))
        self.add_service(CommandExecutionService(bus, 1))
        self.add_service(WiFiScanService(bus, 2))

class PlanesignBLEAdvertisement(Advertisement):
    def __init__(self, bus, index):
        Advertisement.__init__(self, bus, index, 'peripheral')
        self.add_service_uuid(PLANESIGN_MASTER_UUID)
        self.add_local_name(f"PlaneSign-BLE-{get_mac_suffix()}")
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

class CommandCharacteristic(Characteristic):
    COMMAND_CHRC_UUID = '99945678-1234-5678-1234-56789abcdef2'

    # List of allowed commands
    ALLOWED_COMMANDS = {
        'date': '/bin/date',
        'uptime': '/usr/bin/uptime',
        'temp': '/usr/bin/vcgencmd measure_temp',
        'hostname': '/bin/hostname',
        'reboot': 'sudo /usr/sbin/reboot',
        'update': '/home/pi/PlaneSign/docker_install_and_update.sh --reboot > /home/pi/PlaneSign/logs/ble_update.log 2>&1',
    }

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.COMMAND_CHRC_UUID, ['read', 'write'], service)
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
        Characteristic.__init__(self, bus, index, self.WIFI_SCAN_CHRC_UUID, ['read', 'write'], service)
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

def get_mac_suffix(interface='wlan0'):
    cmd = f"cat /sys/class/net/{interface}/address"
    mac_address = subprocess.check_output(cmd, shell=True).decode().strip()
    return mac_address.replace(":", "")[-4:].upper()

if __name__ == '__main__':
    main()