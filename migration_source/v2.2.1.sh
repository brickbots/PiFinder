PIFINDER_REPO_DIR="${PIFINDER_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
source "${PIFINDER_REPO_DIR}/pifinder_paths.sh"

# install lib input
sudo apt install -y libinput10

# Add PiFinder user to input group
sudo usermod -G input -a "${PIFINDER_USER}"
