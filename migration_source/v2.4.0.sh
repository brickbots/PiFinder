PIFINDER_REPO_DIR="${PIFINDER_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
source "${PIFINDER_REPO_DIR}/pifinder_paths.sh"

#Add and enable cedar-detect as system process
pifinder_render_config "${PIFINDER_REPO_DIR}/pi_config_files/cedar_detect.service" /lib/systemd/system/cedar_detect.service
sudo systemctl daemon-reload
sudo systemctl enable cedar_detect
