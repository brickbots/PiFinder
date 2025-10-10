#!/bin/bash
set -e

# Add INDI repository
apt-get update
apt-get install -y software-properties-common
add-apt-repository ppa:mutlaqja/ppa -y
apt-get update

# Install INDI server and components
apt-get install -y \
    indi-bin \
    indi-telescope-simulator \
    libindi-dev \
    swig

# Install Python dependencies
cd /workspaces/PiFinder/python
python3 -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements_dev.txt

# Install PyIndi from git (same as nox sessions)
pip install "git+https://github.com/indilib/pyindi-client.git@v2.1.2#egg=pyindi-client"

# Install indiwebmanager from the same repo/branch as in ~/Projects/PiFinder/indiwebmanager
cd /workspaces
git clone https://github.com/jscheidtmann/indiwebmanager.git
cd indiwebmanager
git checkout control_panel
pip install -e .

# Set up indiwebmanager as a systemd service
# Create service file with current user
CURRENT_USER=$(whoami)
cat > /tmp/indiwebmanager.service <<EOF
[Unit]
Description=INDI Web Manager
After=multi-user.target

[Service]
Type=idle
User=${CURRENT_USER}
ExecStart=/usr/local/bin/indi-web -v
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Install and enable the service
cp /tmp/indiwebmanager.service /etc/systemd/system/
chmod 644 /etc/systemd/system/indiwebmanager.service
systemctl daemon-reload
systemctl enable indiwebmanager.service
systemctl start indiwebmanager.service

echo ""
echo "INDI setup complete!"
echo "INDI Web Manager service has been installed and started."
echo "Check status with: systemctl status indiwebmanager.service"
echo "Access at: http://localhost:8624"
echo ""
echo "To start INDI server directly: indiserver indi_simulator_telescope"
