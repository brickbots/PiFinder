#!/bin/bash
# nixos_migration.sh - Pre-migration: validate, download, stage initramfs
#
# Called by PiFinder app (sys_utils.start_nixos_migration).
# Runs on RPi OS before rebooting into initramfs for the actual migration.
#
# The initramfs will:
#   1. Save WiFi + user backup to RAM
#   2. DD the .img.zst to the SD card
#   3. Expand partition, restore WiFi + user data
#   4. Reboot into NixOS
#
# Usage: nixos_migration.sh <migration_url> [sha256] [progress_file]
#
# Exit codes:
#   0 - Success (initramfs staged, ready to reboot)
#   1 - Pre-flight check failure
#   2 - Download failure
#   3 - Checksum mismatch
#   5 - Initramfs staging failure

set -euo pipefail

export PATH="/usr/sbin:/sbin:${PATH}"

MIGRATION_URL="${1:?Usage: nixos_migration.sh <url> [sha256] [progress_file]}"
MIGRATION_SHA256="${2:-}"
PROGRESS_FILE="${3:-/tmp/nixos_migration_progress}"

trap '_trap_err $LINENO "$BASH_COMMAND"' ERR
_trap_err() {
    echo "{\"percent\": 0, \"status\": \"FAILED at line $1: $2\"}" > "${PROGRESS_FILE}"
    echo "ERROR at line $1: $2" >&2
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PIFINDER_HOME="/home/pifinder"
TARBALL="${PIFINDER_HOME}/pifinder-nixos-migration.tar.zst"
BOOT_PARTITION="/boot"
INITRAMFS_DIR="/tmp/nixos_initramfs"
PROGRESS_BIN="${SCRIPT_DIR}/migration_progress"
INIT_SCRIPT="${SCRIPT_DIR}/nixos_migration_init.sh"

progress() {
    local pct="$1"
    local msg="$2"
    echo "{\"percent\": ${pct}, \"status\": \"${msg}\"}" > "${PROGRESS_FILE}"
    echo "[${pct}%] ${msg}"
}

fail() {
    local code="$1"
    local msg="$2"
    progress 0 "FAILED: ${msg}"
    echo "ERROR: ${msg}" >&2
    exit "${code}"
}

# Copy a binary and all its shared library dependencies into the initramfs.
copy_with_libs() {
    local bin_path="$1"
    local dest="$2"

    cp "${bin_path}" "${dest}/bin/"

    ldd "${bin_path}" 2>/dev/null | grep -oP '/\S+' | while read -r lib; do
        local dir
        dir=$(dirname "${lib}")
        mkdir -p "${dest}${dir}"
        cp -n "${lib}" "${dest}${dir}/" 2>/dev/null || true
    done
}

# --- Phase 0: Install required packages ---
progress 0 "Installing dependencies"
for pkg in e2fsprogs dosfstools fdisk zstd; do
    if ! dpkg -s "${pkg}" >/dev/null 2>&1; then
        sudo apt-get install -y "${pkg}" || fail 1 "Failed to install ${pkg}"
    fi
done

# --- Phase 1: Pre-flight checks ---
progress 3 "Running pre-flight checks"

if ! python3 "${SCRIPT_DIR}/nixos_migration_calc.py" --json > /tmp/migration_checks.json 2>&1; then
    fail 1 "Pre-flight checks failed"
fi

WIFI_MODE=$(python3 -c "import json; print(json.load(open('/tmp/migration_checks.json'))['wifi_mode'])")
if [ "${WIFI_MODE}" != "Client" ]; then
    fail 1 "WiFi must be in Client mode"
fi

# RAM check: image must fit in available RAM during initramfs
MEM_KB=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
MEM_MB=$((MEM_KB / 1024))
[ "${MEM_MB}" -lt 1800 ] && fail 1 "Insufficient RAM: ${MEM_MB}MB (need 2GB)"

progress 5 "Pre-flight OK"

# --- Phase 2: Download image ---
SKIP_DOWNLOAD=false
if [ -f "${TARBALL}" ]; then
    if [ -z "${MIGRATION_SHA256}" ]; then
        progress 60 "Using cached download (no checksum)"
        SKIP_DOWNLOAD=true
    else
        progress 10 "Verifying existing download"
        EXISTING_SHA256=$(sha256sum "${TARBALL}" | awk '{print $1}')
        if [ "${EXISTING_SHA256}" = "${MIGRATION_SHA256}" ]; then
            progress 60 "Using cached download"
            SKIP_DOWNLOAD=true
        fi
    fi
fi

if [ "${SKIP_DOWNLOAD}" = false ]; then
    progress 10 "Downloading... 0%"
    rm -f "${TARBALL}"

    if ! curl -L -f -o "${TARBALL}" \
        --progress-bar \
        "${MIGRATION_URL}" 2>&1 | tr '\r' '\n' | while IFS= read -r line; do
            if [[ "$line" =~ ([0-9]+)\.[0-9]% ]]; then
                dl_pct="${BASH_REMATCH[1]}"
                mapped_pct=$(( 10 + dl_pct * 50 / 100 ))
                progress "${mapped_pct}" "Downloading... ${dl_pct}%"
            fi
        done; then
        fail 2 "Download failed"
    fi

    # --- Phase 3: Verify checksum ---
    if [ -z "${MIGRATION_SHA256}" ]; then
        progress 60 "SHA256 not provided, skipping verification"
    else
        progress 60 "Verifying checksum"
        ACTUAL_SHA256=$(sha256sum "${TARBALL}" | awk '{print $1}')
        if [ "${ACTUAL_SHA256}" != "${MIGRATION_SHA256}" ]; then
            rm -f "${TARBALL}"
            fail 3 "Checksum mismatch"
        fi
    fi
fi

progress 65 "Download OK"

# --- Phase 4: Get image size ---
progress 68 "Preparing"

TARBALL_SIZE=$(stat -c%s "${TARBALL}")

progress 75 "Tarball: $((TARBALL_SIZE / 1048576))MB"

# --- Phase 5: Build initramfs ---
progress 78 "Building initramfs"

rm -rf "${INITRAMFS_DIR}"
mkdir -p "${INITRAMFS_DIR}"/{bin,lib,dev,proc,sys,mnt,tmp}

# Busybox (provides sh, mount, umount, dd, tar, cp, etc.)
if command -v busybox >/dev/null 2>&1; then
    copy_with_libs "$(command -v busybox)" "${INITRAMFS_DIR}"
else
    fail 5 "busybox not found"
fi

# Filesystem tools
for tool in e2fsck resize2fs mke2fs mkfs.vfat sfdisk zstd; do
    tool_path=$(command -v "${tool}" 2>/dev/null || true)
    if [ -z "${tool_path}" ]; then
        fail 5 "${tool} not found — install e2fsprogs dosfstools util-linux zstd"
    fi
    copy_with_libs "${tool_path}" "${INITRAMFS_DIR}"
done

# mkfs.ext4 is typically a symlink to mke2fs
ln -sf mke2fs "${INITRAMFS_DIR}/bin/mkfs.ext4" 2>/dev/null || true

# OLED progress display (static binary, no libs needed)
cp "${PROGRESS_BIN}" "${INITRAMFS_DIR}/bin/" 2>/dev/null || true

# SPI kernel modules — needed for OLED progress display
# Modules may be compressed (.ko.xz); decompress for insmod in initramfs
KVER=$(uname -r)
KMOD_DIR="/lib/modules/${KVER}/kernel/drivers/spi"
if [ -d "${KMOD_DIR}" ]; then
    INITRAMFS_SPI="${INITRAMFS_DIR}/lib/modules"
    mkdir -p "${INITRAMFS_SPI}"
    for mod in spi-bcm2835 spidev; do
        if [ -f "${KMOD_DIR}/${mod}.ko.xz" ]; then
            xz -dc "${KMOD_DIR}/${mod}.ko.xz" > "${INITRAMFS_SPI}/${mod}.ko"
        elif [ -f "${KMOD_DIR}/${mod}.ko.gz" ]; then
            gzip -dc "${KMOD_DIR}/${mod}.ko.gz" > "${INITRAMFS_SPI}/${mod}.ko"
        elif [ -f "${KMOD_DIR}/${mod}.ko.zst" ]; then
            zstd -dc "${KMOD_DIR}/${mod}.ko.zst" > "${INITRAMFS_SPI}/${mod}.ko"
        elif [ -f "${KMOD_DIR}/${mod}.ko" ]; then
            cp "${KMOD_DIR}/${mod}.ko" "${INITRAMFS_SPI}/${mod}.ko"
        fi
    done
fi

# Dynamic linker — needed for non-busybox tools
LD_PATH=$(find /lib /lib64 /usr/lib -name "ld-linux-*" -type f 2>/dev/null | head -1 || true)
if [ -n "${LD_PATH}" ]; then
    mkdir -p "${INITRAMFS_DIR}$(dirname "${LD_PATH}")"
    cp "${LD_PATH}" "${INITRAMFS_DIR}${LD_PATH}"
fi

# Init script
cp "${INIT_SCRIPT}" "${INITRAMFS_DIR}/init"
chmod +x "${INITRAMFS_DIR}/init"

# Metadata: paths + sizes so init script knows where to find things
cat > "${INITRAMFS_DIR}/migration_meta" <<METAEOF
TARBALL_PATH=${TARBALL}
TARBALL_SIZE=${TARBALL_SIZE}
PIFINDER_DATA_PATH=${PIFINDER_HOME}/PiFinder_data
METAEOF

progress 85 "Staging initramfs"

# --- Phase 6: Create and stage initramfs ---
cd "${INITRAMFS_DIR}"
find . | cpio -o -H newc 2>/dev/null | gzip > /tmp/nixos_migration_initramfs.gz

sudo cp /tmp/nixos_migration_initramfs.gz "${BOOT_PARTITION}/initramfs-migration.gz"

# Migration flag on boot partition (survives root format)
sudo touch "${BOOT_PARTITION}/nixos_migration"

progress 92 "Configuring boot"

# --- Phase 7: Configure boot to use migration initramfs ---
if [ -f "${BOOT_PARTITION}/config.txt" ]; then
    sudo cp "${BOOT_PARTITION}/config.txt" "${BOOT_PARTITION}/config.txt.premigration"

    echo "initramfs initramfs-migration.gz followkernel" | \
        sudo tee -a "${BOOT_PARTITION}/config.txt" > /dev/null
fi

progress 100 "Rebooting in 5s..."

echo "Migration staged. Tarball: ${TARBALL_SIZE} bytes"
echo "Rebooting in 5 seconds..."
sleep 5
sudo reboot
