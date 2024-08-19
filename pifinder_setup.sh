#! /usr/bin/bash
sudo apt-get install -y git python3-pip samba samba-common-bin dnsmasq hostapd dhcpd gpsd

git clone --recursive --branch release https://github.com/brickbots/PiFinder.git
cd PiFinder
sudo pip install -r python/requirements.txt

# Setup GPSD
sudo dpkg-reconfigure -plow gpsd
sudo cp ~/PiFinder/pi_config_files/gpsd.conf /etc/default/gpsd

# data dirs
mkdir ~/PiFinder_data
mkdir ~/PiFinder_data/captures
mkdir ~/PiFinder_data/obslists
mkdir ~/PiFinder_data/screenshots
mkdir ~/PiFinder_data/solver_debug_dumps
mkdir ~/PiFinder_data/logs
chmod -R 777 ~/PiFinder_data

# Wifi config
sudo cp ~/PiFinder/pi_config_files/dhcpcd.* /etc
sudo cp ~/PiFinder/pi_config_files/dhcpcd.conf.sta /etc/dhcpcd.conf
sudo cp ~/PiFinder/pi_config_files/dnsmasq.conf /etc/dnsmasq.conf
sudo cp ~/PiFinder/pi_config_files/hostapd.conf /etc/hostapd/hostapd.conf
echo -n "Client" > ~/PiFinder/wifi_status.txt
sudo systemctl unmask hostapd

# open permissisons on wpa_supplicant file so we can adjust network config
sudo chmod 666 /etc/wpa_supplicant/wpa_supplicant.conf

# Samba config
sudo cp ~/PiFinder/pi_config_files/smb.conf /etc/samba/smb.conf

# Hipparcos catalog
wget -O /home/pifinder/PiFinder/astro_data/hip_main.dat https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat

# Enable interfaces
echo "dtparam=spi=on" | sudo tee -a /boot/config.txt
echo "dtparam=i2c_arm=on" | sudo tee -a /boot/config.txt
echo "dtparam=i2c_arm_baudrate=10000" | sudo tee -a /boot/config.txt
echo "dtoverlay=pwm,pin=13,func=4" | sudo tee -a /boot/config.txt
echo "dtoverlay=uart3" | sudo tee -a /boot/config.txt

# Enable service
sudo cp /home/pifinder/PiFinder/pi_config_files/pifinder.service /lib/systemd/system/pifinder.service
sudo cp /home/pifinder/PiFinder/pi_config_files/pifinder_splash.service /lib/systemd/system/pifinder_splash.service
sudo systemctl daemon-reload
sudo systemctl enable pifinder
sudo systemctl enable pifinder_splash

echo "PiFinder setup complete, please restart the Pi"

