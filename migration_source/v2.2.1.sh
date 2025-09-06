# install lib input
sudo apt install -y libinput10

# Add PiFinder user to input group
sudo usermod -G input -a "pifinder"

