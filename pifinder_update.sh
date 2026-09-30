#! /usr/bin/bash
cd /home/pifinder/PiFinder || exit 1
git checkout release
if ! git pull
then
    echo "PiFinder software update FAILED: the new version could not be downloaded."
    echo "The currently installed version is unchanged. See the git error above."
    exit 1
fi
source /home/pifinder/PiFinder/pifinder_post_update.sh

echo "PiFinder software update complete, please restart the Pi"
