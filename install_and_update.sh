#!/bin/bash

# This aim of this script is to be idempotent

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
  sudo bash -c "echo ' isolcpus=3' >> /boot/cmdline.txt"
else
  echo "isolcpus config found in /boot/cmdline.txt"
fi

# Turn off onboard audio
sudo sed -i 's/dtparam=audio=on/dtparam=audio=off/' /boot/config.txt

# apt install system packages
sudo apt install -y git nginx python3-venv python3-pip python3-dev python3-pil libatlas-base-dev ffmpeg libffi-dev

# Install rpi-rgb-led-matrix
LED_MATRIX_DIR="${INSTALL_DIR}/rpi-rgb-led-matrix"
if [[ ! -d $LED_MATRIX_DIR ]]
then
  echo "rpi-rgb-led-matrix not found, installing..."
  git clone https://github.com/hzeller/rpi-rgb-led-matrix.git $LED_MATRIX_DIR
  cd $LED_MATRIX_DIR
  git reset --hard 87a9caba561bf94ac15f6fe7e492ed7bcbcb58a2
  make build-python PYTHON=$(which python3)
  sudo make install-python PYTHON=$(which python3)
else
  echo "rpi-rgb-led-matrix already installed"
fi

# Install PlaneSign git repo
PLANESIGN_DIR="${INSTALL_DIR}/PlaneSign"
cd $PLANESIGN_DIR
git pull --rebase --autostash https://github.com/dmod/PlaneSign

#Install required junk
sudo apt -y install llvm-14 llvm14-dev
sudo -H LLVM_CONFIG=/usr/lib/llvm14/bin/llvm-config pip3 install --break-system-packages llvmlite numba

#Install packages
#sudo -H pip3 install -r requirements.txt
while IFS= read -r package; do
  if [ -n "$package" ]; then
    sudo -H pip3 install --break-system-packages "$package"
  fi
done < requirements.txt

# Update cache
./update_static_cache.py

# Create a self-signed cert for HTTPS
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /etc/ssl/private/planesign-selfsigned.key -out /etc/ssl/certs/planesign-selfsigned.crt -subj "/C=US"
sudo cp self-signed.conf /etc/nginx/snippets/

# Clear out old nginx configurations, install updated config, restart nginx
sudo rm -f /etc/nginx/sites-available/default
sudo rm -f /etc/nginx/sites-enabled/default
sudo cp nginx_planesign.conf /etc/nginx/conf.d/
chmod +x /home/pi/PlaneSign/
sudo systemctl restart nginx

# Cron config for starting the process on boot
(crontab -u pi -l ; echo "@reboot sleep 10 && cd /home/pi/PlaneSign && sudo python3 planesign>/dev/null 2>&1") | sort - | uniq - | crontab -u pi -

echo "Installation and configuration completed!"

if [[ "$1" == "--reboot" ]]
then
  echo "...Rebooting"
  sudo reboot
fi
