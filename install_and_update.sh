#!/bin/bash

# This aim of this script is to be idempotent

# Stop on first error
set -e

# to skip any questions from APT
export DEBIAN_FRONTEND=noninteractive

INSTALL_DIR=/home/pi

echo "PlaneSign install starting..."

sudo apt-get update -y

# Performance upgrade for isolcpus
grep "isolcpus" /boot/cmdline.txt
if [ $? -ne 0 ]
then
  echo "Adding isolcpus config to /boot/cmdline.txt"
  sudo echo " isolcpus=3" >> /boot/cmdline.txt
else
  echo "isolcpus config found in /boot/cmdline.txt"
fi

# Turn off onboard audio
sudo sed -i 's/dtparam=audio=on/dtparam=audio=off/' /boot/config.txt

sudo apt install -y git nginx python3-venv python3-pip python3-dev python3-pil libatlas-base-dev ffmpeg

# Install rpi-rgb-led-matrix
LED_MATRIX_DIR="${INSTALL_DIR}/rpi-rgb-led-matrix"
if [ ! -d $LED_MATRIX_DIR ] 
then
  echo "rpi-rgb-led-matrix not found, installing..."
  git clone https://github.com/hzeller/rpi-rgb-led-matrix.git $LED_MATRIX_DIR
  cd $LED_MATRIX_DIR
  make build-python PYTHON=$(which python3)
  sudo make install-python PYTHON=$(which python3)
else
  echo "rpi-rgb-led-matrix already installed"
fi

PLANESIGN_DIR="${INSTALL_DIR}/PlaneSign"
cd $PLANESIGN_DIR
git pull --rebase --autostash http://dmod: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@github.com/dmod/PlaneSign
sudo -H pip3 install -r requirements.txt

sudo ./update_static_cache.py

sudo cp nginx_planesign.conf /etc/nginx/sites-available/default

(crontab -u pi -l ; echo "@reboot sleep 10 && cd /home/pi/PlaneSign && sudo python3 planesign>/dev/null 2>&1") | sort - | uniq - | crontab -u pi -

echo "Installation and configuration completed!"
