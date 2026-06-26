#! /usr/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp /etc/dhcpcd.conf.ap /etc/dhcpcd.conf
systemctl enable dnsmasq
systemctl enable hostapd
echo -n "AP" > "${SCRIPT_DIR}/wifi_status.txt"
#systemctl start dnsmasq
#systemctl start hostapd
#systemctl restart dhcpcd
