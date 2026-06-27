#!/usr/bin/bash
# This script installs the PiFinder software on a prepared Raspberry Pi OS.
# See https://pifinder.readthedocs.io/en/release/software.html for more info.

set -e

if [[ "$(id -u)" -eq 0 ]]; then
    echo "Do not run this script with sudo." >&2
    echo "Run it as the target OS user; the script will use sudo when needed." >&2
    exit 1
fi

PIFINDER_USER="${PIFINDER_USER:-${SUDO_USER:-$(id -un)}}"
if [[ "${PIFINDER_USER}" == "root" ]]; then
    echo "Run as the target OS user, or set PIFINDER_USER=<user>." >&2
    exit 1
fi

PIFINDER_HOME="$(getent passwd "${PIFINDER_USER}" | cut -d: -f6)"
if [[ -z "${PIFINDER_HOME}" || ! -d "${PIFINDER_HOME}" ]]; then
    echo "Could not determine home directory for ${PIFINDER_USER}" >&2
    exit 1
fi

cd "${PIFINDER_HOME}"

sudo bash -c '
set -e
trap "rm -f /usr/sbin/policy-rc.d" EXIT
printf "%s\n" "#!/bin/sh" "exit 101" > /usr/sbin/policy-rc.d
chmod 755 /usr/sbin/policy-rc.d
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git python3-pip python3-venv python3-dev build-essential pkg-config \
    samba samba-common-bin dnsmasq hostapd dhcpcd gpsd wget \
    libinput10 libcap2-bin libjpeg-dev zlib1g-dev libfreetype6-dev \
    liblcms2-dev libopenjp2-7-dev libtiff-dev libffi-dev libssl-dev \
    python3-picamera2 rpicam-apps i2c-tools spi-tools
'

if [[ -d PiFinder/ ]]; then
    cd PiFinder/ && git config pull.rebase false && git pull
else
    git clone --recursive --branch release https://github.com/brickbots/PiFinder.git
fi

PIFINDER_REPO_DIR="${PIFINDER_HOME}/PiFinder"
source "${PIFINDER_REPO_DIR}/pifinder_paths.sh"

cd "${PIFINDER_REPO_DIR}"
sudo python3 -m pip install --break-system-packages -r python/requirements.txt

# Setup GPSD
sudo cp "${PIFINDER_REPO_DIR}/pi_config_files/gpsd.conf" /etc/default/gpsd

# Data dirs
sudo install -d -o "${PIFINDER_USER}" -g "${PIFINDER_USER}" -m 755 \
    "${PIFINDER_DATA_DIR}" \
    "${PIFINDER_DATA_DIR}/captures" \
    "${PIFINDER_DATA_DIR}/obslists" \
    "${PIFINDER_DATA_DIR}/screenshots" \
    "${PIFINDER_DATA_DIR}/solver_debug_dumps" \
    "${PIFINDER_DATA_DIR}/logs" \
    "${PIFINDER_DATA_DIR}/migrations"

# Wifi config
sudo cp "${PIFINDER_REPO_DIR}"/pi_config_files/dhcpcd.* /etc
sudo cp "${PIFINDER_REPO_DIR}/pi_config_files/dhcpcd.conf.sta" /etc/dhcpcd.conf
sudo cp "${PIFINDER_REPO_DIR}/pi_config_files/dnsmasq.conf" /etc/dnsmasq.conf
sudo cp "${PIFINDER_REPO_DIR}/pi_config_files/hostapd.conf" /etc/hostapd/hostapd.conf
echo -n "Client" > "${PIFINDER_REPO_DIR}/wifi_status.txt"
sudo systemctl unmask hostapd

# Open permissions on wpa_supplicant file so we can adjust network config.
sudo install -d -m 755 /etc/wpa_supplicant
sudo touch /etc/wpa_supplicant/wpa_supplicant.conf
sudo chmod 666 /etc/wpa_supplicant/wpa_supplicant.conf

# Samba config
pifinder_render_config "${PIFINDER_REPO_DIR}/pi_config_files/smb.conf" /etc/samba/smb.conf

# Hipparcos catalog
HIP_MAIN_DAT="${PIFINDER_REPO_DIR}/astro_data/hip_main.dat"
if [[ ! -e $HIP_MAIN_DAT ]]; then
    wget -O $HIP_MAIN_DAT https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat
fi

# Enable interfaces
BOOT_CONFIG="$(pifinder_boot_config_path)"
grep -q "dtparam=spi=on" "${BOOT_CONFIG}" || \
   echo "dtparam=spi=on" | sudo tee -a "${BOOT_CONFIG}"
grep -q "dtparam=i2c_arm=on" "${BOOT_CONFIG}" || \
   echo "dtparam=i2c_arm=on" | sudo tee -a "${BOOT_CONFIG}"
grep -q "dtparam=i2c_arm_baudrate=10000" "${BOOT_CONFIG}" || \
   echo "dtparam=i2c_arm_baudrate=10000" | sudo tee -a "${BOOT_CONFIG}"
grep -q "dtoverlay=pwm,pin=13,func=4" "${BOOT_CONFIG}" || \
   echo "dtoverlay=pwm,pin=13,func=4" | sudo tee -a "${BOOT_CONFIG}"
grep -q "dtoverlay=uart3" "${BOOT_CONFIG}" || \
   echo "dtoverlay=uart3" | sudo tee -a "${BOOT_CONFIG}"

# Power-off latch (rev-4): at kernel poweroff drive GPIO14 low -> LTC2954 KILL ->
# TPS61088 boost EN off -> power cut. active_low + the hardware pull-up on GPIO14
# keep the pin high (power on) through boot/reboot. No-op on rev-3. See ADR 0007.
grep -q "dtoverlay=gpio-poweroff" "${BOOT_CONFIG}" || \
   echo "dtoverlay=gpio-poweroff,gpiopin=14,active_low" | sudo tee -a "${BOOT_CONFIG}"

# Free GPIO14 (UART0 TXD) for the power-off latch: drop the serial console so the
# kernel doesn't drive console bytes onto the kill line. Leaves enable_uart/BT alone.
sudo sed -i 's/console=serial0,[0-9]\+ //' /boot/cmdline.txt
sudo systemctl mask serial-getty@ttyAMA0.service

# Note: camera types are added lateron by python/PiFinder/switch_camera.py

# Disable unwanted services
sudo systemctl disable ModemManager 2>/dev/null || true
sudo systemctl disable dhcpcd dnsmasq hostapd 2>/dev/null || true

# Enable service
pifinder_render_config "${PIFINDER_REPO_DIR}/pi_config_files/pifinder.service" /lib/systemd/system/pifinder.service
pifinder_render_config "${PIFINDER_REPO_DIR}/pi_config_files/pifinder_splash.service" /lib/systemd/system/pifinder_splash.service
pifinder_render_config "${PIFINDER_REPO_DIR}/pi_config_files/cedar_detect.service" /lib/systemd/system/cedar_detect.service
sudo systemctl daemon-reload
sudo systemctl enable cedar_detect
sudo systemctl enable pifinder
sudo systemctl enable pifinder_splash

for group in input video render dialout gpio i2c spi; do
    if getent group "${group}" >/dev/null; then
        sudo usermod -aG "${group}" "${PIFINDER_USER}"
    fi
done

echo "PiFinder setup complete, please restart the Pi"
