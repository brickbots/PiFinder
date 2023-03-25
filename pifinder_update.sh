#! /usr/bin/bash
git pull
sudo pip install -r /home/pifinder/PiFinder/requirements.txt
source /home/pifinder/PiFinder/pifinder_post_update.sh

echo "PiFinder software update complete, please restart the Pi"

