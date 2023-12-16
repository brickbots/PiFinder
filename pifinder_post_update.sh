git submodule update --init --recursive

# open permissisons on wpa_supplicant file so we can adjust network config
sudo chmod 666 /etc/wpa_supplicant/wpa_supplicant.conf

# DONE
echo "Post Update Complete"

