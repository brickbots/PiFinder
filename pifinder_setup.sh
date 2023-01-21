#! /usr/bin/bash
sudo apt-get install -y git python3-pip
git clone https://github.com/brickbots/PiFinder.git
cd PiFinder
sudo pip install -r requirements.txt
cd python/PiFinder
git clone https://github.com/esa/tetra3.git
echo "dtparam=spi=on" | sudo tee -a /boot/config.txt
echo "dtparam=i2c_arm=on" | sudo tee -a /boot/config.txt
echo "dtparam=i2c_arm_baudrate=10000" | sudo tee -a /boot/config.txt
