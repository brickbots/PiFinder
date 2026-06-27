#! /usr/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#systemctl stop dnsmasq
#systemctl stop hostapd
cp /etc/dhcpcd.conf.sta /etc/dhcpcd.conf
systemctl disable dnsmasq
systemctl disable hostapd
#systemctl restart dhcpcd
echo -n "Client" > "${SCRIPT_DIR}/wifi_status.txt"
