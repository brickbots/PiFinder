git submodule update --init --recursive

# GPSD
sudo apt install -y gpsd
sudo dpkg-reconfigure -plow gpsd

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

# DONE
echo "Post Update Complete"

