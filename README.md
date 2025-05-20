# PlaneSign

[![CI to Docker Hub](https://github.com/dmod/PlaneSign/actions/workflows/pipeline.yml/badge.svg)](https://github.com/dmod/PlaneSign/actions/workflows/pipeline.yml)

![Image](.data/planesign.jpeg)

## Hardware Requirements

- Raspberry Pi 4 (2GB is sufficient)
- 2x 64x32 RGB LED Matrix - Either 4mm or 5mm pitch ([Adafruit Link](https://www.adafruit.com/product/2277))
- 5V 10A 50W Power Supply (100V-240V AC to DC Adapter)
- 15 female-to-female breadboard jumper wires (150mm recommended)
- 3D printed components:
  - [L-bracket](.data/adjustable_L_bracket.stl) for panel attachment
  - Rectangle spacer (~4mm) for panel spacing
- Wood components:
  - 1" x 4" board (minimum 6ft length)
  - Top piece: 25 3/16"
  - Side piece: 6 5/16" (for 5mm pitch)
- Hardware:
  - Socket cap screws (M3-0.5 x 16mm)
  - #4S flat washers for spacing
- [Wiring Instructions](https://github.com/hzeller/rpi-rgb-led-matrix/blob/master/wiring.md)

## Software Setup

### Initial SD Card Setup
1. Flash SD card with [Raspberry PI OS Lite](https://peppe8o.com/install-raspberry-pi-os-lite-in-your-raspberry-pi/)
2. In the 'boot' folder on the SD card:
   - Create empty `ssh` file
   - Disable on-board sound by adding `dtparam=audio=off` to `/boot/config.txt`
   - Add `isolcpus=3` to the end of `/boot/cmdline.txt`
   - Set up [wpa_supplicant.conf](https://www.raspberrypi.com/documentation/computers/configuration.html#adding-the-network-details-to-your-raspberry-pi)
3. Insert SD card into Raspberry Pi
4. (Recommended) Change hostname to 'planesign':
   ```
   sudo raspi-config -> System Options -> Hostname
   ```

### Installation Options

#### Docker Installation
```sh
cd /home/pi && git clone https://github.com/dmod/PlaneSign && ./PlaneSign/docker_install_and_update.sh --reboot
```

#### Classic Installation
```sh
cd /home/pi && git clone https://github.com/dmod/PlaneSign && ./PlaneSign/install_and_update.sh
```

### Sample wpa_supplicant.conf
Location: `/etc/wpa_supplicant/wpa_supplicant.conf`
```
country=US
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
ap_scan=1

update_config=1
network={
    ssid="PlainTextSSID"
    psk=Result-Of-NtPasswordHash
}
```

## Technical Notes
- Update static cache: `./update_static_cache.py`
- Text positioning:
  - X,Y coordinates represent bottom-left corner of characters
  - (0,0) is top-left of RGB matrix
- Demo test command:
  ```sh
  sudo rpi-rgb-led-matrix/examples-api-use/demo --led-slowdown-gpio=4 --led-cols=64 --led-chain=2 -D4
  ```
- 5mm spacing: approximately 26¾" × 8" overall
- [Feature request](https://issuetracker.google.com/issues/35822507) for Google Geocode API landmark returns

## Credits

### Data Providers
- OpenWeather™
- FlightRadar24
- ucsusa.org
- n2yo.com
- coinmarketcap.com
- googleapis.com
- ourairports.com
- opendatasoft.com (map polygons)
- [Natural Earth Vector](https://github.com/nvkelso/natural-earth-vector/tree/master/geojson) (countries and water bodies)
- open-elevation.com

### Sound Resources
- freesoundslibrary.com
- freesound.org
- zapsplat.com
- myinstants.com
- pixabay.com
