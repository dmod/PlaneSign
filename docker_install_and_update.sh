#!/bin/bash

if [ "$USER" = root ]; then
    echo "This script shouldn't be run as root. Aborting."
    exit 1
fi

# to skip any questions from APT
export DEBIAN_FRONTEND=noninteractive

INSTALL_DIR=/home/pi

echo "PlaneSign install starting..."

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
if lsmod | grep -wq "snd_bcm2835"; then
  echo "snd_bcm2835 is loaded!"
  sudo rmmod snd_bcm2835
fi
sudo sed -i 's/dtparam=audio=on/dtparam=audio=off/' /boot/config.txt

# Stop existing versions of nginx
sudo systemctl disable nginx
crontab -r

# Install bluetooth support
sudo ln --force --symbolic /home/pi/PlaneSign/ble/planesign-ble.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable planesign-ble.service

# Add Docker's official GPG key:
sudo apt-get update
sudo apt-get -y install ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --batch --yes --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo groupadd --force docker
sudo usermod -aG docker $USER
# newgrp docker

sudo systemctl enable docker.service
sudo systemctl enable containerd.service

if [ ! -f /home/pi/PlaneSign/sign.conf ]; then
  cp /home/pi/PlaneSign/sign.conf.sample /home/pi/PlaneSign/sign.conf
fi

sudo docker pull dmod/planesign:latest
sudo docker rm --force PlaneSignRuntime # Stops and removes any existing container
sudo docker run --detach --restart unless-stopped --name PlaneSignRuntime --privileged -p 80:80 -p 443:443 --mount type=bind,source=/home/pi/PlaneSign/sign.conf,target=/planesign/sign.conf dmod/planesign:latest

echo "Installation and configuration completed!"

if [[ "$1" == "--reboot" ]]
then
  echo "...Rebooting"
  sudo reboot
fi
