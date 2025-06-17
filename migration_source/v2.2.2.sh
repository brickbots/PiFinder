# Enable usb-host on usb-c port

#Add it to the dw2 line if it exist
sudo sed -zi "s/dtoverlay=dwc2\n/dtoverlay=dwc2,dr_mode=host\n/" /boot/config.txt

#Add the line if it does not exist
sudo sed -zi '/dtoverlay=dwc2,dr_mode=host\n/!s/$/\ndtoverlay=dwc2,dr_mode=host\n/' /boot/config.txt
