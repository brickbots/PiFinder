#! /usr/bin/bash
systemctl stop dnsmasq
systemctl stop hostapd
systemctl disable dnsmasq
systemctl disable hostapd
cp /etc/dhcpcd.conf.sta /etc/dhcpcd.conf
systemctl restart dhcpcd
