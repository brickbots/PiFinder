#!/bin/bash
set -e

# Add INDI repository
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository ppa:mutlaqja/ppa -y
sudo apt update
sudo apt upgrade -y

# Install INDI server and components
sudo apt install -y \
    indi-bin \
    libindi-dev \
    swig \
    libdbus-1-3 \
    libdbus-1-dev \
    libglib2.0-0t64 \
    libglib2.0-bin \
    libglib2.0-dev \
    python-setuptools \
    python-dev \
    libindi-dev \
    libcfitsio-dev \
    libnova-dev

# Install Python dependencies
cd /workspaces/PiFinder/python
python3 -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements_dev.txt

# Install working PyIndi client from git
pip install "git+https://github.com/indilib/pyindi-client.git@v2.1.2#egg=pyindi-client"

# Install indiwebmanager from the "control_panel" branch from jscheidtmann's fork
sudo pip install "git+https://github.com/jscheidtmann/indiwebmanager.git@control_panel#egg=indiwebmanager"

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
sudo cp /tmp/indiwebmanager.service /etc/systemd/system/
sudo chmod 644 /etc/systemd/system/indiwebmanager.service
sudo systemctl daemon-reload
sudo systemctl enable indiwebmanager.service
sudo systemctl start indiwebmanager.service

echo ""
echo "INDI setup complete!"
echo "INDI Web Manager service has been installed and started."
echo "Check status with: systemctl status indiwebmanager.service"
echo "Access at: http://localhost:8624"
echo ""
echo "To start INDI server directly: indiserver indi_simulator_telescope"
