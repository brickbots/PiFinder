#! /usr/bin/bash
sudo apt-get install -y git python3-pip samba samba-common-bin gpsd python3-picamera2

git clone --recursive --branch bookworm https://github.com/brickbots/PiFinder.git
cd PiFinder
python -m venv --system-site-packages python/venv
source python/venv/bin/activate
pip install -r requirements.txt

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
echo -n "Client" > ~/PiFinder/wifi_status.txt

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

