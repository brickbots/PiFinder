#! /usr/bin/bash
git checkout release
git pull
source /home/pifinder/PiFinder/pifinder_post_update.sh

echo "PiFinder software update complete, please restart the Pi"

