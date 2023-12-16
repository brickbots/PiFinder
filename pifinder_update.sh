#! /usr/bin/bash
git checkout release
git pull
git submodule update --init --recursive
source /home/pifinder/PiFinder/python/venv/bin/activate
pip install -r /home/pifinder/PiFinder/requirements.txt
source /home/pifinder/PiFinder/pifinder_post_update.sh

echo "PiFinder software update complete, please restart the Pi"

