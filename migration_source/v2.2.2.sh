PIFINDER_REPO_DIR="${PIFINDER_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
source "${PIFINDER_REPO_DIR}/pifinder_paths.sh"

# Enable usb-host on usb-c port
BOOT_CONFIG="$(pifinder_boot_config_path)"

#Add it to the dw2 line if it exist
sudo sed -zi "s/dtoverlay=dwc2\n/dtoverlay=dwc2,dr_mode=host\n/" "${BOOT_CONFIG}"

#Add the line if it does not exist
sudo sed -zi '/dtoverlay=dwc2,dr_mode=host\n/!s/$/\ndtoverlay=dwc2,dr_mode=host\n/' "${BOOT_CONFIG}"
