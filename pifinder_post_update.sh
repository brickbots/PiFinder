sudo apt install -y gpsd
sudo dpkg-reconfigure -plow gpsd
sudo sed -zi '/dtoverlay=pwm,pin=13,func=4\n/!s/$/\ndtoverlay=pwm,pin=13,func=4\n/' /boot/config.txt
echo "Post Update Complete"

