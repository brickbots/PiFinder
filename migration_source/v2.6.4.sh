# Gate the gpio-poweroff overlay to the CM4 (rev4) — see ADR 0034.
# On Pi 4B units (v3 and earlier) the ungated overlay replaces the firmware
# power-off with a GPIO handler nothing answers: poweroff WARNs after ~3s and
# parks the kernel with the screen still lit. [cm4] is matched from the board
# revision code, so only the rev4 loads the overlay.
if ! grep -q "^\[cm4\]" /boot/config.txt
then
    sudo sed -i '/^dtoverlay=gpio-poweroff/d' /boot/config.txt
    printf '[cm4]\ndtoverlay=gpio-poweroff,gpiopin=14,active_low\n[all]\n' | sudo tee -a /boot/config.txt
fi
