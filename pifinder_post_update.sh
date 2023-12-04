git submodule update --init --recursive

# GPSD
sudo apt install -y gpsd
sudo dpkg-reconfigure -plow gpsd
sudo cp ~/PiFinder/pi_config_files/gpsd.conf /etc/default/gpsd

# PWM
sudo sed -zi '/dtoverlay=pwm,pin=13,func=4\n/!s/$/\ndtoverlay=pwm,pin=13,func=4\n/' /boot/config.txt

# Migrate DB
if [ -f "/home/pifinder/PiFinder/astro_data/observations.db" ]
then
    echo "Migrating astro_data DB"
    python -c "from PiFinder import setup;setup.create_logging_tables();"
    sqlite3 < /home/pifinder/PiFinder/migrate_db.sql
    rm /home/pifinder/PiFinder/astro_data/observations.db
fi

# Migrate Config files
if ! [ -f "/home/pifinder/PiFinder_data/config.json" ]
then
    echo "Migrating config.json"
    mv /home/pifinder/PiFinder/config.json /home/pifinder/PiFinder_data/config.json
fi

# Adjust service definition
sudo systemctl disable pifinder
sudo cp /home/pifinder/PiFinder/pi_config_files/pifinder.service /lib/systemd/system/pifinder.service
sudo systemctl daemon-reload
sudo systemctl enable pifinder

# add PiFinder_splash if not already in place
if ! [ -f "/lib/systemd/system/pifinder_spash.service" ]
then
    sudo cp /home/pifinder/PiFinder/pi_config_files/pifinder_splash.service /lib/systemd/system/pifinder_splash.service
    sudo systemctl daemon-reload
    sudo systemctl enable pifinder_splash
fi

# open permissisons on wpa_supplicant file so we can adjust network config
sudo chmod 666 /etc/wpa_supplicant/wpa_supplicant.conf

# DONE
echo "Post Update Complete"

