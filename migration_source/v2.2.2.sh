# Enable usb-host on usb-c port
sudo sed -zi "s/dtoverlay=dwc2/dtoverlay=dwc2,dr_mode=host/" /boot/config.txt

