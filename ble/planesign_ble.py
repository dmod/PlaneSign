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
        self.add_characteristic(PlanesignWiFiStatusCharacteristic(bus, 3, self))

class CommandExecutionService(Service):
    def __init__(self, bus, index):
        Service.__init__(self, bus, index, '312f08be-a717-40b0-9730-6d3d7c929856', True)
        self.add_characteristic(CommandCharacteristic(bus, 0, self))

class WiFiScanService(Service):
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
        try:
            # Convert the received bytes to string
            credentials = bytes(value).decode().strip()
            print('WiFiConfigCharacteristic Write: Received credentials')
            
            # Expected format: "SSID|PASSWORD"
            if '|' not in credentials:
                raise ValueError("Invalid format. Expected 'SSID|PASSWORD'")
                
            ssid, password = credentials.split('|', 1)
            
            # Delete existing connection with the same SSID if it exists
            subprocess.run(['sudo', 'nmcli', 'connection', 'delete', ssid], 
                         stderr=subprocess.DEVNULL)  # Ignore errors if connection doesn't exist
            
            # Add new connection
            subprocess.run([
                'sudo', 'nmcli', 'connection', 'add',
                'type', 'wifi',
                'con-name', ssid,
                'ifname', 'wlan0',
                'ssid', ssid,
                'wifi-sec.key-mgmt', 'wpa-psk',
                'wifi-sec.psk', password
            ], check=True)
            
            # Enable and bring up the connection
            subprocess.run(['sudo', 'nmcli', 'connection', 'up', ssid], check=True)
            
            print(f'Successfully configured WiFi network: {ssid}')
            
        except subprocess.CalledProcessError as e:
            error_msg = f"NetworkManager error: {str(e)}"
            print(error_msg)
            raise dbus.exceptions.DBusException(error_msg)
        except Exception as e:
            error_msg = f"Error configuring WiFi: {str(e)}"
            print(error_msg)
            raise dbus.exceptions.DBusException(error_msg)

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

class PlanesignWiFiStatusCharacteristic(Characteristic):
    CHRC_UUID = 'f2a3b4c5-6d7e-8f90-a1b2-c3d4e5f6a7b8'

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.CHRC_UUID, ['read'], service)

    def ReadValue(self, options):
        wifi_status = self.get_wifi_status()
        print('WiFi Status Read: ' + wifi_status)
        return [dbus.Byte(x.encode()) for x in wifi_status]

    def get_wifi_status(self):
        try:
            # Get current WiFi connection info using nmcli
            connection_info = subprocess.check_output(
                ['nmcli', '-t', '-f', 'ACTIVE,SSID,SIGNAL', 'dev', 'wifi', 'list', '--rescan', 'no'],
                stderr=subprocess.DEVNULL
            ).decode('utf-8').strip()
            
            # Find the currently connected network (marked as active)
            connected_network = None
            for line in connection_info.split('\n'):
                if line.startswith('yes:'):
                    parts = line.split(':')
                    if len(parts) >= 3:
                        ssid = parts[1] if parts[1] else 'Hidden Network'
                        signal = parts[2] if parts[2] else '0'
                        connected_network = f"{ssid}|{signal}"
                        break
            
            if connected_network:
                return f"Connected|{connected_network}"
            else:
                return "Disconnected|None|0"
                
        except subprocess.CalledProcessError:
            # Fallback to iwconfig if nmcli fails
            try:
                iwconfig_output = subprocess.check_output(
                    ['iwconfig', 'wlan0'], 
                    stderr=subprocess.DEVNULL
                ).decode('utf-8')
                
                # Extract SSID and signal strength from iwconfig output
                ssid = 'Unknown'
                signal = '0'
                
                # Parse ESSID
                import re
                essid_match = re.search(r'ESSID:"([^"]*)"', iwconfig_output)
                if essid_match:
                    ssid = essid_match.group(1)
                
                # Parse signal level
                signal_match = re.search(r'Signal level=(-?\d+)', iwconfig_output)
                if signal_match:
                    signal = signal_match.group(1)
                
                # Check if connected (has an IP address)
                if 'Access Point:' in iwconfig_output and 'Not-Associated' not in iwconfig_output:
                    return f"Connected|{ssid}|{signal}"
                else:
                    return "Disconnected|None|0"
                    
            except subprocess.CalledProcessError:
                return "Error|Unable to get WiFi status|0"

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
            # Use iw to scan
            cmd_output = subprocess.check_output(['sudo', 'iw', 'dev', 'wlan0', 'scan'], 
                                              stderr=subprocess.STDOUT).decode('utf-8')
            
            # Parse the output to get networks
            networks = []
            current_network = {}
            
            for line in cmd_output.split('\n'):
                line = line.strip()
                if 'BSS' in line and '(' in line:  # New network found
                    if current_network.get('ssid'):  # Save previous network if it had an SSID
                        networks.append(f"{current_network['ssid']}|{current_network.get('signal', 'N/A')}|{current_network.get('quality', 'N/A')}|{current_network.get('encrypted', 'yes')}")
                    current_network = {}
                elif 'SSID:' in line:
                    ssid = line.split('SSID:', 1)[1].strip()
                    if ssid:  # Only store non-empty SSIDs
                        current_network['ssid'] = ssid
                elif 'signal:' in line:
                    current_network['signal'] = line.split('signal:', 1)[1].strip().split()[0]  # Gets the dBm value
            
            # Add the last network if it exists
            if current_network.get('ssid'):
                networks.append(f"{current_network['ssid']}|{current_network.get('signal', 'N/A')}|{current_network.get('quality', 'N/A')}|{current_network.get('encrypted', 'yes')}")
            
            print(f"Found {len(networks)} networks")
            self.last_scan = "\n".join(networks[:6]) if networks else "No networks found"
            
        except subprocess.CalledProcessError as e:
            self.last_scan = f"Error scanning WiFi: {str(e)}"
        except Exception as e:
            self.last_scan = f"Unexpected error: {str(e)}"

    def ReadValue(self, options):
        print('WiFiScanCharacteristic Read requested')
        print(f'LastScan size: {len(self.last_scan)}')
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