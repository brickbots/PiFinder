#! /usr/bin/bash
sudo apt-get install -y git python3-pip samba samba-common-bin dnsmasq hostapd dhcpd gpsd
sudo dpkg-reconfigure -plow gpsd
git clone --recursive --branch release https://github.com/brickbots/PiFinder.git
cd PiFinder
sudo pip install -r requirements.txt

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
echo -n "Cli" > ~/PiFinder/wifi_status.txt
sudo systemctl unmask hostapd

# Samba config
sudo cp ~/PiFinder/pi_config_files/smb.conf /etc/samba/smb.conf

# Hipparcos catalog
wget -O /home/pifinder/PiFinder/astro_data/hip_main.dat https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat

# Enable interfaces
echo "dtparam=spi=on" | sudo tee -a /boot/config.txt
echo "dtparam=i2c_arm=on" | sudo tee -a /boot/config.txt
echo "dtparam=i2c_arm_baudrate=10000" | sudo tee -a /boot/config.txt
echo "dtoverlay=pwm,pin=13,func=4" | sudo tee -a /boot/config.txt

# Enable service
sudo cp /home/pifinder/PiFinder/pifinder.service /etc/systemd/system/pifinder.service
sudo systemctl daemon-reload
sudo systemctl enable pifinder

echo "PiFinder setup complete, please restart the Pi"

