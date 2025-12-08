#Add and enable cedar-detect as system process
sudo cp /home/pifinder/PiFinder/pi_config_files/cedar_detect.service /lib/systemd/system/cedar_detect.service
sudo systemctl daemon-reload
sudo systemctl enable cedar_detect
