#!/bin/bash

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "This installer must be run as root."
    exit 1
fi

# to skip any questions from APT
export DEBIAN_FRONTEND=noninteractive

RUN_USER=pi
RUN_GROUP=pi

HOME_DIR="/home/$RUN_USER"
INSTALL_DIR="$HOME_DIR/PlaneSign"

GITHUB_BASE_URL="${GITHUB_BASE_URL:-https://raw.githubusercontent.com/dmod/PlaneSign/main}"

COMPOSE_FILE="$INSTALL_DIR/compose.yaml"
CONTAINER_NAME=PlaneSignRuntime

download_required_file() {
  local url="$1"
  local destination="$2"
  local temporary

  echo "Downloading $url"
  temporary="$(mktemp "${destination}.tmp.XXXXXX")"
  if wget -q --show-progress -O "$temporary" "$url"; then
    mv "$temporary" "$destination"
    chmod 644 "$destination"
    chown "$RUN_USER:$RUN_GROUP" "$destination"
  else
    rm -f "$temporary"
    echo "Failed to download $url" >&2
    exit 1
  fi
}

remove_existing_planesign_container() {
  if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    echo "Removing existing $CONTAINER_NAME container before Compose recreates it..."
    docker rm --force "$CONTAINER_NAME"
  fi
}

echo "PlaneSign install starting..."

if [ -f /boot/firmware/cmdline.txt ]; then
  BOOT_DIR=/boot/firmware
else
  BOOT_DIR=/boot
fi

CMDLINE_FILE="$BOOT_DIR/cmdline.txt"
CONFIG_FILE="$BOOT_DIR/config.txt"

# Performance upgrade for isolcpus
if [ -f "$CMDLINE_FILE" ] && ! grep -qw "isolcpus" "$CMDLINE_FILE"; then
  echo "Adding isolcpus config to $CMDLINE_FILE"
  sed -i '$ s/$/ isolcpus=3/' "$CMDLINE_FILE"
elif [ -f "$CMDLINE_FILE" ]; then
  echo "isolcpus config found in $CMDLINE_FILE"
else
  echo "Warning: $CMDLINE_FILE not found; skipping isolcpus config"
fi

# Turn off onboard audio
if lsmod | grep -wq "snd_bcm2835"; then
  echo "snd_bcm2835 is loaded!"
  rmmod snd_bcm2835
fi
if [ -f "$CONFIG_FILE" ]; then
  sed -i 's/dtparam=audio=on/dtparam=audio=off/' "$CONFIG_FILE"
else
  echo "Warning: $CONFIG_FILE not found; skipping onboard audio config"
fi
if [ ! -f /etc/modprobe.d/alsa-blacklist.conf ] || ! grep -q "blacklist snd_bcm2835" /etc/modprobe.d/alsa-blacklist.conf; then
  echo "Blacklisting snd_bcm2835 module..."
  echo "blacklist snd_bcm2835" | tee -a /etc/modprobe.d/alsa-blacklist.conf
else
  echo "snd_bcm2835 already blacklisted"
fi

# Stop existing versions of nginx (from legacy non-Docker installs)
if systemctl list-unit-files nginx.service &>/dev/null && systemctl list-unit-files nginx.service | grep -q nginx; then
  echo "Legacy nginx service found, disabling..."
  systemctl disable nginx
fi

# Download required files from GitHub
BLE_DIR="$INSTALL_DIR/ble"
install -d \
    -o "$RUN_USER" \
    -g "$RUN_GROUP" \
    -m 755 \
    "$INSTALL_DIR"

install -d \
    -o "$RUN_USER" \
    -g "$RUN_GROUP" \
    -m 755 \
    "$BLE_DIR"
for file in __init__.py gatt.py planesign_ble.py planesign-ble.service wifi.py; do
  download_required_file "$GITHUB_BASE_URL/ble/$file" "$BLE_DIR/$file"
done

download_required_file "$GITHUB_BASE_URL/sign.conf.sample" "$INSTALL_DIR/sign.conf.sample"
download_required_file "$GITHUB_BASE_URL/compose.yaml" "$COMPOSE_FILE"

# Install bluetooth support
apt-get update

apt-get install -y \
    bluez \
    python3-dbus

systemctl daemon-reload
systemctl enable bluetooth.service >/dev/null 2>&1 || true
systemctl is-active --quiet bluetooth.service || \
    systemctl start bluetooth.service
rfkill unblock bluetooth || \
    echo "Warning: unable to unblock Bluetooth"
(echo "power on"; echo "quit") | bluetoothctl >/dev/null 2>&1 || true

ln --force --symbolic "$INSTALL_DIR/ble/planesign-ble.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable planesign-ble.service

# Verify bluetooth adapter status
echo "Bluetooth status:"
rfkill list bluetooth | grep -E "Soft|Hard" || echo "  Warning: no rfkill Bluetooth status found"
bluetoothctl show 2>/dev/null | grep -E "Name|Powered|Address" || echo "  Warning: no adapter found"

# Add Docker's official GPG key:
apt-get -y install ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --batch --yes --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update

apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

groupadd --force docker
usermod -aG docker "$RUN_USER"

systemctl enable docker.service
systemctl enable containerd.service

if [ ! -f "$INSTALL_DIR/sign.conf" ]; then
  install \
    -o "$RUN_USER" \
    -g "$RUN_GROUP" \
    -m 644 \
    "$INSTALL_DIR/sign.conf.sample" \
    "$INSTALL_DIR/sign.conf"
fi

# Create persistent host directories and seed them from the PlaneSign git source.
temp_clone="$(mktemp -d)"
git clone --depth 1 https://github.com/dmod/PlaneSign.git "$temp_clone"
for dir in datafiles sketches icons; do
    install -d \
        -o "$RUN_USER" \
        -g "$RUN_GROUP" \
        -m 755 \
        "$INSTALL_DIR/$dir"

    if [ -d "$temp_clone/$dir" ]; then
        cp -a "$temp_clone/$dir/." "$INSTALL_DIR/$dir/"
        chown -R "$RUN_USER:$RUN_GROUP" "$INSTALL_DIR/$dir"
    fi
done
rm -rf "$temp_clone"

docker compose -f "$COMPOSE_FILE" config >/dev/null
docker compose -f "$COMPOSE_FILE" pull
remove_existing_planesign_container
docker compose -f "$COMPOSE_FILE" up --detach --force-recreate --remove-orphans

chown -R "$RUN_USER:$RUN_GROUP" "$INSTALL_DIR"

echo "Installation and configuration completed! Rebooting..."
sync
reboot
