# PlaneSign

![Image](.data/planesign.jpeg)

## Hardware To Buy

- Raspberry Pi 4 (2GB is fine)
- 2x 64x32 RGB LED Matrix = EITHER the 4mm or 5mm pitch <https://www.adafruit.com/product/2277>
- 5V 10A 50W Power Supply 100V-240V AC to DC Adapter
- 1 inch x 4 inch >= 6ft board - Cut board top piece is 25 inch 3/16 inch, side piece is 6 and 5/16 inch (for 5 MM pitch)
- 3D print a rectangle spacer, ~4mm back from front of wood
- Socket cap screw M3-0.5 x 16mm to secure sign
- #4S flat washers for fine spacing
- Wire it up using jumper cables: <https://github.com/hzeller/rpi-rgb-led-matrix/blob/master/wiring.md>

## Software Setup Steps

- Flash SD card with Raspberry PI OS Lite - <https://peppe8o.com/install-raspberry-pi-os-lite-in-your-raspberry-pi/>
- touch ssh
- Set up wpa_supplicant.conf: <https://www.raspberrypi.org/documentation/configuration/wireless/headless.md>
- **Now put it in the actual pi**
- (RECOMMENDED): Change hostname with: sudo raspi-config -> System Options -> Hostname
- (RECOMMENDED): Change timezone with: sudo raspi-config -> Localisation Options -> Timezone
- Switch off on-board sound `dtparam=audio=off` in /boot/config.txt

```sh
sudo apt install -y git nginx python3-venv python3-pip python3-dev python3-pillow
git clone https://github.com/hzeller/rpi-rgb-led-matrix.git
cd rpi-rgb-led-matrix
make build-python PYTHON=$(which python3)
sudo make install-python PYTHON=$(which python3)
cd
sudo -H pip3 install pytz flask flask_cors
git clone https://github.com/dmod/PlaneSign.git
sudo ./planesign.py
```

crontab -e:

```sh
@reboot sleep 10 && cd /home/pi/PlaneSign && sudo python3 planesign.py>/dev/null 2>&1
```

/etc/nginx/sites-available/default:

```sh
server {
        listen 80 default_server;
        listen [::]:80 default_server;

        root /home/pi/PlaneSign/web;

        index index.html index.htm index.nginx-debian.html;

        server_name _;

        location / {
                add_header 'Access-Control-Allow-Origin' '*';
                try_files $uri $uri/ =404;
        }

        location /api/ {
                rewrite /api/(.*) /$1  break;
                proxy_pass         http://localhost:5000;
                proxy_redirect     off;
                proxy_set_header   Host $host;
        }
}
```

## Random Notes

wget <https://ourairports.com/data/airports.csv>
FONTS ARE MEASURED FROM BOTTOM LEFT?
DEMO TEST: sudo rpi-rgb-led-matrix/examples-api-use/demo --led-slowdown-gpio=3 --led-cols=64 --led-chain=2 -D4
5mm spacing: approx 26 3/4 inches X 8 overall
<https://issuetracker.google.com/issues/140786115>
