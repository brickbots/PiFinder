#! /usr/bin/bash
git checkout release
git pull
git submodule update --init --recursive
sudo pip install -r $HOME/PiFinder/requirements.txt
source $HOME/PiFinder/pifinder_post_update.sh

echo "PiFinder software update complete, please restart the Pi"

