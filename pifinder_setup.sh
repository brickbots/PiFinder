#! /usr/bin/bash
sudo apt-get install -y git python3-pip
git clone --branch main https://github.com/brickbots/PiFinder.git
cd PiFinder
sudo pip install -r requirements.txt

# data dirs
mkdir ~/PiFinder_data
mkdir ~/PiFinder_data/captures
mkdir ~/PiFinder_data/obslists
mkdir ~/PiFinder_data/screnshots
mkdir ~/PiFinder_data/solver_debug_dumps
mkdir ~/PiFinder_data/logs

# Hipparcos catalog
wget -O /home/pifinder/PiFinder/astro_data/hip_main.dat https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat

# Tetra3 solver
cd python/PiFinder
git clone https://github.com/esa/tetra3.git

# Enable interfaces
echo "dtparam=spi=on" | sudo tee -a /boot/config.txt
echo "dtparam=i2c_arm=on" | sudo tee -a /boot/config.txt
echo "dtparam=i2c_arm_baudrate=10000" | sudo tee -a /boot/config.txt

# Enable service
sudo cp /home/pifinder/PiFinder/pifinder.service /etc/systemd/system/pifinder.service
sudo systemctl daemon-reload
sudo systemctl enable pifinder

echo "PiFinder setup complete, please restart the Pi"

