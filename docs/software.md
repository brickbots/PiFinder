General Pi Setup
* Create Image
	* Pi OS Lite 64
	* Setup SSh / Wifi
![Raspberry Pi Imager settings](../images/raspi_imager_settings.png)
* Setup terminfo for kitty:
	* `kitty +kitten ssh pifinder@pifinder.local`
* Login first time
* Update all packages
	* `sudo apt update`
	* `sudo apt upgrade`
* Clock stretching - https://learn.adafruit.com/circuitpython-on-raspberrypi-linux/i2c-clock-stretching
**  Maybe not needed any longer with updated firmware?  Need to test

Packages
* pytz-2022.7.1
* timezonefinder-6.1.9
* luma.oled-3.9.0
* skyfield-1.45
* scipy-1.10.0
* pynmea2-1.19.0
* adafruit-blinka-8.12.0
* adafruit-circuitpython-bno055
* pandas-1.5.3

Data
* Stellerium constellation data
* Hipparcos catalog - https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat
* Yale BSA

Script
* install git (sudo apt install git)
* install pip (sudo apt install python3-pip)
* git clone pifinder repo (https)
* sudo pip install deps
* Git clone tetra3 into PiFinder/python/PiFinder
	* git clone https://github.com/esa/tetra3.git
* enable spi / i2c
	* `echo "dtparam=spi=on" | sudo tee -a /boot/config.txt
	* `echo "dtparam=i2c_arm=on" | sudo tee -a /boot/config.txt`
	* `echo "dtparam=i2c1=on" | sudo tee -a /boot/config.txt`
* Run python script to invoke enough of AstoPy so that it downloads the data files it needs. Add this to setup.py
* Setup PiFinder system service
