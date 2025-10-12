
set -e

echo "Starting INDI installation..."
echo "This script installs INDI and INDI Web Manager on your PiFinder."
echo "It may take some time depending on your internet speed and system performance."
echo ""

echo "==============================================================================="
echo "PiFinder: Updating system packages..."
echo "==============================================================================="
sudo apt update
sudo apt upgrade -y

#
# Build indi
#
echo "==============================================================================="
echo "PiFinder: Installing dependencies for INDI..."
echo "==============================================================================="

sudo apt install -y \
    git \
    cdbs \
    dkms \
    cmake \
    fxload \
    libev-dev \
    libgps-dev \
    libgsl-dev \
    libraw-dev \
    libusb-dev \
    zlib1g-dev \
    libftdi-dev \
    libjpeg-dev \
    libkrb5-dev \
    libnova-dev \
    libtiff-dev \
    libfftw3-dev \
    librtlsdr-dev \
    libcfitsio-dev \
    libgphoto2-dev \
    build-essential \
    libusb-1.0-0-dev \
    libdc1394-dev \
    libboost-regex-dev \
    libcurl4-gnutls-dev \
    libtheora-dev

echo "==============================================================================="
echo "PiFinder: Compiling INDI..."
echo "==============================================================================="
cd ~
# Latest release tag as of 2025-10-12
git clone --branch v2.1.6 --depth 1 https://github.com/indilib/indi.git
mkdir -p ./indi/build
cd ./indi/build
cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr ..
# Deactivate pifinder service during build phase.
sudo systemctl stop pifinder
make -j2
sudo make install
sudo systemctl start pifinder

#
# Build and install indiwebmanager
# 
echo "==============================================================================="
echo "PiFinder: Dependencies for indiwebmanager..."
echo "==============================================================================="

sudo apt install -y \
    swig \
    libdbus-1-3 \
    libdbus-1-dev \
    libglib2.0-0 \
    libglib2.0-bin \
    libglib2.0-dev \
    python-setuptools \
    python-dev-is-python3

echo "==============================================================================="
echo "PiFinder: Install indiwebmanager..."
echo "==============================================================================="

sudo pip install FastAPI uvicorn

sudo pip install "git+https://github.com/indilib/pyindi-client.git@v2.1.2#egg=pyindi-client"
sudo pip install "git+https://github.com/jscheidtmann/indiwebmanager.git@control_panel#vegg=indiwebmanager"

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

echo "==============================================================================="
echo "PiFinder: Install time synchronization..."
echo "==============================================================================="

sudo apt install chrony
sudo echo "# Sync time from GPSD" >> /etc/chrony/chrony.conf
sudo echo "refclock SHM 0 poll 3 refid gps1" >> /etc/chrony/chrony.conf
sudo systemctl restart chrony

echo "==============================================================================="
echo "PiFinder: INDI setup complete!"
echo "==============================================================================="
echo ""
echo "INDI Web Manager service has been installed and started."
echo "Please check status with: systemctl status indiwebmanager.service"
echo "Access at: http://localhost:8624 or http://<your-pifinder-ip>:8624"
echo ""
echo "Set Timezone appropriate with 'sudo raspi-config'!"

