# Switch tetra 3 to submodule
if test -f "/home/pifinder/PiFinder/python/PiFinder/tetra3/default_database.npz"; then
    echo "Switching Tetra3"
    rm -rf /home/pifinder/PiFinder/python/PiFinder/tetra3
    git submodule update --init
fi

# GPSD
sudo apt install -y gpsd
sudo dpkg-reconfigure -plow gpsd

# PWM
sudo sed -zi '/dtoverlay=pwm,pin=13,func=4\n/!s/$/\ndtoverlay=pwm,pin=13,func=4\n/' /boot/config.txt

# DONE
echo "Post Update Complete"

