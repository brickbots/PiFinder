#! /usr/bin/bash
cp /etc/dhcpcd.conf.ap /etc/dhcpcd.conf
systemctl enable dnsmasq
systemctl enable hostapd
echo -n "AP" > /home/pifinder/PiFinder/wifi_status.txt
#systemctl start dnsmasq
#systemctl start hostapd
#systemctl restart dhcpcd
