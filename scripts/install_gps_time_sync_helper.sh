#!/usr/bin/env bash
# Install or manage the optional privileged GPS time-sync helper service.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIFINDER_REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${PIFINDER_REPO_DIR}/pifinder_paths.sh"

SERVICE_NAME="pifinder_gps_time_sync.service"
SERVICE_TEMPLATE="${PIFINDER_REPO_DIR}/pi_config_files/${SERVICE_NAME}"
SERVICE_TARGET="/lib/systemd/system/${SERVICE_NAME}"

install_service() {
    pifinder_render_config "${SERVICE_TEMPLATE}" "${SERVICE_TARGET}"
    sudo systemctl daemon-reload
    echo "Installed ${SERVICE_NAME}"
}

case "${1:-install}" in
    install)
        install_service
        echo "Service installed but not enabled."
        echo "Run: $0 enable"
        ;;
    enable)
        install_service
        sudo systemctl enable --now "${SERVICE_NAME}"
        ;;
    disable)
        sudo systemctl disable --now "${SERVICE_NAME}" 2>/dev/null || true
        ;;
    restart)
        install_service
        sudo systemctl restart "${SERVICE_NAME}"
        ;;
    status)
        systemctl status "${SERVICE_NAME}" --no-pager
        ;;
    *)
        echo "Usage: $0 {install|enable|disable|restart|status}" >&2
        exit 2
        ;;
esac
