import subprocess
import dbus.exceptions

class WiFiNetwork:
    def __init__(self, ssid, signal='N/A', quality='N/A', encrypted='yes'):
        self.ssid = ssid
        self.signal = signal
        self.quality = quality
        self.encrypted = encrypted
    
    def get_signal_int(self):
        try:
            return int(self.signal)
        except (ValueError, TypeError):
            return -100  # Very weak signal for sorting
    
    def __str__(self):
        return f"{self.ssid}|{self.signal}|{self.quality}|{self.encrypted}"

def get_wifi_status():
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
        return "Error|Unable to get WiFi status|0"

def scan_wifi():
    try:
        print("Scanning WiFi...")
        # Use iw to scan - it shows all available networks unlike nmcli
        cmd_output = subprocess.check_output(['sudo', 'iw', 'dev', 'wlan0', 'scan'], 
                                          stderr=subprocess.STDOUT).decode('utf-8')
        
        networks = []
        current_network = {}
        
        for line in cmd_output.split('\n'):
            line = line.strip()
            if 'BSS' in line and '(' in line:  # New network found
                if current_network.get('ssid'):  # Save previous network if it had an SSID
                    network = WiFiNetwork(
                        ssid=current_network['ssid'],
                        signal=current_network.get('signal', 'N/A'),
                        quality='N/A',
                        encrypted=current_network.get('encrypted', 'yes')
                    )
                    networks.append(network)
                current_network = {}
            elif 'SSID:' in line:
                ssid = line.split('SSID:', 1)[1].strip()
                if ssid:  # Only store non-empty SSIDs
                    current_network['ssid'] = ssid
            elif 'signal:' in line:
                current_network['signal'] = line.split('signal:', 1)[1].strip().split()[0]  # Gets the dBm value
        
        # Add the last network if it exists
        if current_network.get('ssid'):
            network = WiFiNetwork(
                ssid=current_network['ssid'],
                signal=current_network.get('signal', 'N/A'),
                quality='N/A',
                encrypted=current_network.get('encrypted', 'yes')
            )
            networks.append(network)
        
        # Group networks by SSID and keep the best one
        # Duplicates occur due to: dual-band (2.4/5GHz), multiple APs, different security modes
        unique_networks = {}
        for network in networks:
            if network.ssid not in unique_networks:
                unique_networks[network.ssid] = network
            else:
                current = unique_networks[network.ssid]
                # Prefer 2.4GHz for better range, fall back to stronger signal
                signal_diff = network.get_signal_int() - current.get_signal_int()
                if signal_diff > 0 or (abs(signal_diff) <= 15 and current.get_signal_int() > -40):
                    # Keep the new one if it's stronger, or likely weaker 2.4GHz with decent range
                    unique_networks[network.ssid] = network
        
        # Sort by signal strength (best first) and take top 10
        sorted_networks = sorted(unique_networks.values(), key=lambda net: net.get_signal_int(), reverse=True)
        top_networks = sorted_networks[:10]
        
        print(f"Found {len(networks)} networks ({len(unique_networks)} unique), returning top {len(top_networks)}")
        return "\n".join(str(network) for network in top_networks) if top_networks else "No networks found"
        
    except subprocess.CalledProcessError as e:
        return f"Error scanning WiFi: {str(e)}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"

def configure_wifi(credentials):
    try:
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