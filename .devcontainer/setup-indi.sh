#!/bin/bash
set -e

####
#### Install development environment in GitHub codespace.
####

# Add INDI repository
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository ppa:mutlaqja/ppa -y
sudo apt update
sudo apt upgrade -y

# Install INDI server and components
# python-setuptools \
# libglib2.0-0t64 \
sudo apt install -y \
    indi-bin \
    libindi-dev \
    swig \
    libdbus-1-3 \
    libdbus-1-dev \
    libglib2.0-0 \
    libglib2.0-bin \
    libglib2.0-dev \
    python-dev-is-python3 \
    libindi-dev \
    libcfitsio-dev \
    libnova-dev \
    pkg-config \
    meson \
    ninja-build \
    build-essential

# Install Python dependencies
cd /workspaces/PiFinder/python
python3 -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements_dev.txt

# Install working PyIndi client from git
pip install "git+https://github.com/indilib/pyindi-client.git@v2.1.2#egg=pyindi-client"

# Install indiwebmanager from the "control_panel" branch from jscheidtmann's fork
pip install fastapi uvicorn jinja2 aiofiles
pip install "git+https://github.com/jscheidtmann/indiwebmanager.git@control_panel#egg=indiweb"

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
/usr/local/python/3.9.25/bin/indi-web &

cd /workspaces
git clone --depth 1 https://github.com/indilib/indi.git
git clone --depth 1 https://github.com/indilib/indi-3rdparty.git
