import re

class WiFiScanner:
    def __init__(self):
        pass

    def scan_wifi_networks(self):
        networks = []
        with open('/etc/network/interfaces', 'r') as file:
            content = file.read()
            iface_matches = re.findall(r'iface\s+(\w+)\s+inet\s+dhcp', content)
            for iface in iface_matches:
                network_info = {'interface': iface}
                ssid_match = re.search(r'wpa-ssid\s+"([^"]+)"', content)
                if ssid_match:
                    network_info['ssid'] = ssid_match.group(1)
                else:
                    network_info['ssid'] = "Open Network"
                networks.append(network_info)
        return networks

if __name__ == "__main__":
    wifi_scanner = WiFiScanner()
    networks = wifi_scanner.scan_wifi_networks()
    for network in networks:
        print("Interface:", network['interface'], "SSID:", network['ssid'])
