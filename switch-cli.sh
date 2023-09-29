#! /usr/bin/bash
#systemctl stop dnsmasq
#systemctl stop hostapd
cp /etc/dhcpcd.conf.sta /etc/dhcpcd.conf
systemctl disable dnsmasq
systemctl disable hostapd
#systemctl restart dhcpcd
echo -n "Cli" > $HOME/PiFinder/wifi_status.txt
shutdown -r now
