git submodule update --init --recursive
sudo pip install -r /home/pifinder/PiFinder/python/requirements.txt

# Set up migrations folder if it does not exist
if ! [ -d "/home/pifinder/PiFinder_data/migrations" ]
then
    mkdir /home/pifinder/PiFinder_data/migrations
fi

# v1.x.x
# everying prior to selecitve migrations
if ! [ -f "/home/pifinder/PiFinder_data/migrations/v1.x.x" ]
then
    source /home/pifinder/PiFinder/migration_source/v1.x.x.sh
    touch /home/pifinder/PiFinder_data/migrations/v1.x.x
fi

# v2.1.0
# Switch to Cedar
if ! [ -f "/home/pifinder/PiFinder_data/migrations/v2.1.0" ]
then
    source /home/pifinder/PiFinder/migration_source/v2.1.0.sh
    touch /home/pifinder/PiFinder_data/migrations/v2.1.0
fi

# v2.2.1
# Install libinput
if ! [ -f "/home/pifinder/PiFinder_data/migrations/v2.2.1" ]
then
    source /home/pifinder/PiFinder/migration_source/v2.2.1.sh
    touch /home/pifinder/PiFinder_data/migrations/v2.2.1
fi

# v2.2.2
# Enable host usb on usb-c port
if ! [ -f "/home/pifinder/PiFinder_data/migrations/v2.2.2" ]
then
    source /home/pifinder/PiFinder/migration_source/v2.2.2.sh
    touch /home/pifinder/PiFinder_data/migrations/v2.2.2
fi

# DONE
echo "Post Update Complete"

