#!/usr/bin/env bash
# Shared path helpers for PiFinder shell install/update scripts.

set -e

if [[ -z "${PIFINDER_REPO_DIR:-}" ]]; then
    PIFINDER_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [[ -z "${PIFINDER_USER:-}" ]]; then
    if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
        PIFINDER_USER="${SUDO_USER}"
    else
        PIFINDER_USER="$(id -un)"
    fi
fi

if [[ "${PIFINDER_USER}" == "root" ]]; then
    echo "PiFinder must be installed for a non-root OS user." >&2
    echo "Set PIFINDER_USER=<user> when running as root." >&2
    exit 1
fi

if [[ -z "${PIFINDER_HOME:-}" ]]; then
    PIFINDER_HOME="$(getent passwd "${PIFINDER_USER}" | cut -d: -f6)"
fi

if [[ -z "${PIFINDER_HOME}" || ! -d "${PIFINDER_HOME}" ]]; then
    echo "Could not determine home directory for ${PIFINDER_USER}" >&2
    exit 1
fi

PIFINDER_DATA_DIR="${PIFINDER_DATA_DIR:-${PIFINDER_HOME}/PiFinder_data}"

export PIFINDER_USER
export PIFINDER_HOME
export PIFINDER_REPO_DIR
export PIFINDER_DATA_DIR

pifinder_render_config() {
    local source_file="$1"
    local target_file="$2"

    sudo sed \
        -e "s|__PIFINDER_USER__|${PIFINDER_USER}|g" \
        -e "s|__PIFINDER_HOME__|${PIFINDER_HOME}|g" \
        -e "s|__PIFINDER_REPO_DIR__|${PIFINDER_REPO_DIR}|g" \
        -e "s|__PIFINDER_DATA_DIR__|${PIFINDER_DATA_DIR}|g" \
        "${source_file}" | sudo tee "${target_file}" >/dev/null
}

pifinder_boot_config_path() {
    if [[ -e /boot/firmware/config.txt ]]; then
        printf "%s\n" "/boot/firmware/config.txt"
    else
        printf "%s\n" "/boot/config.txt"
    fi
}
