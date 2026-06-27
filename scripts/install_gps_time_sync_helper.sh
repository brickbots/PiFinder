#!/usr/bin/env bash
# Install or manage the optional privileged GPS time-sync helper service.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIFINDER_REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${PIFINDER_REPO_DIR}/pifinder_paths.sh"

SERVICE_NAME="pifinder_gps_time_sync.service"
SERVICE_TEMPLATE="${PIFINDER_REPO_DIR}/pi_config_files/${SERVICE_NAME}"
SERVICE_TARGET="/lib/systemd/system/${SERVICE_NAME}"
SERVICE_DROPIN_DIR="/etc/systemd/system/${SERVICE_NAME}.d"
DRY_RUN_DROPIN="${SERVICE_DROPIN_DIR}/dry-run.conf"

install_service() {
    pifinder_render_config "${SERVICE_TEMPLATE}" "${SERVICE_TARGET}"
    sudo systemctl daemon-reload
    echo "Installed ${SERVICE_NAME}"
}

install_dry_run_override() {
    sudo install -d -m 755 "${SERVICE_DROPIN_DIR}"
    printf "%s\n" \
        "[Service]" \
        "ExecStart=" \
        "ExecStart=/usr/bin/python -m PiFinder.gps_time_sync_helper --dry-run" \
        | sudo tee "${DRY_RUN_DROPIN}" >/dev/null
    sudo systemctl daemon-reload
    echo "Installed dry-run override for ${SERVICE_NAME}"
}

remove_dry_run_override() {
    sudo rm -f "${DRY_RUN_DROPIN}"
    sudo rmdir "${SERVICE_DROPIN_DIR}" 2>/dev/null || true
    sudo systemctl daemon-reload
}

case "${1:-install}" in
    install)
        install_service
        echo "Service installed but not enabled."
        echo "Run: $0 enable"
        ;;
    enable)
        install_service
        remove_dry_run_override
        sudo systemctl enable --now "${SERVICE_NAME}"
        ;;
    enable-dry-run)
        install_service
        install_dry_run_override
        sudo systemctl enable --now "${SERVICE_NAME}"
        ;;
    disable)
        sudo systemctl disable --now "${SERVICE_NAME}" 2>/dev/null || true
        remove_dry_run_override
        ;;
    restart)
        install_service
        sudo systemctl restart "${SERVICE_NAME}"
        ;;
    restart-dry-run)
        install_service
        install_dry_run_override
        sudo systemctl restart "${SERVICE_NAME}"
        ;;
    status)
        systemctl status "${SERVICE_NAME}" --no-pager
        ;;
    *)
        echo "Usage: $0 {install|enable|enable-dry-run|disable|restart|restart-dry-run|status}" >&2
        exit 2
        ;;
esac
