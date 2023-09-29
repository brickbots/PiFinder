#! /usr/bin/bash
cp /etc/dhcpcd.conf.ap /etc/dhcpcd.conf
echo -n "AP" > $HOME/PiFinder/wifi_status.txt
systemctl enable dnsmasq
systemctl enable hostapd
#systemctl start dnsmasq
#systemctl start hostapd
#systemctl restart dhcpcd
shutdown -r now
