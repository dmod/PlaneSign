#!/bin/bash

# This aim of this script is to be idempotent

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
sudo sed -i 's/dtparam=audio=on/dtparam=audio=off/' /boot/config.txt

# Stop existing versions of nginx
sudo systemctl disable nginx

# Add Docker's official GPG key:
sudo apt-get update
sudo apt-get install ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo groupadd docker
sudo usermod -aG docker $USER
newgrp docker

docker pull dmod/planesign:latest

docker run --detach --restart unless-stopped --privileged -p 80:80 --mount type=bind,source=/home/pi/PlaneSign/sign.conf,target=/planesign/sign.conf dmod/planesign:latest

sudo systemctl enable docker.service
sudo systemctl enable containerd.service

echo "Installation and configuration completed!"

if [[ "$1" == "--reboot" ]]
then
  echo "...Rebooting"
  sudo reboot
fi