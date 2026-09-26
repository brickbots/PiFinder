#!/bin/bash
# nixos_migration.sh - Pre-migration: validate, download, stage initramfs
#
# Called by PiFinder app (sys_utils.start_nixos_migration).
# Runs on RPi OS before rebooting into initramfs for the actual migration.
#
# The initramfs (nixos_migration_init.sh) will:
#   1. Save WiFi and the camera type to RAM
#   2. Grow partition 2, convert its ext4 to btrfs in place
#   3. Move PiFinder_data into a subvolume, remove Pi OS, extract NixOS
#   4. Reboot into NixOS
#
# Usage: nixos_migration.sh <migration_url> [sha256] [progress_file] [display_class] [display_resolution]
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
DISPLAY_CLASS="${4:-}"
DISPLAY_RESOLUTION="${5:-}"

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

    copy_libs "${bin_path}" "${dest}"
}

# Copy only the shared library dependencies of a binary into the initramfs.
copy_libs() {
    local bin_path="$1"
    local dest="$2"

    ldd "${bin_path}" 2>/dev/null | grep -oP '/\S+' | while read -r lib; do
        local dir
        dir=$(dirname "${lib}")
        mkdir -p "${dest}${dir}"
        cp -n "${lib}" "${dest}${dir}/" 2>/dev/null || true
    done
}

# --- Phase 0: Install required packages ---
progress 0 "Installing dependencies"
MISSING_PKGS=""
for pkg in btrfs-progs busybox cpio curl dosfstools e2fsprogs fdisk gzip xz-utils zstd; do
    if ! dpkg -s "${pkg}" >/dev/null 2>&1; then
        MISSING_PKGS="${MISSING_PKGS} ${pkg}"
    fi
done
# The oldest btrfs-progs the migration is tested with (Debian 11 ships
# 5.10.1; nixos/tests/migration-e2e on the NixOS line runs it).
MIN_BTRFS_PROGS="5.10"
btrfs_progs_version() {
    dpkg-query -W -f='${Version}' btrfs-progs 2>/dev/null || true
}
btrfs_progs_ok() {
    local v
    v=$(btrfs_progs_version)
    [ -n "${v}" ] && dpkg --compare-versions "${v}" ge "${MIN_BTRFS_PROGS}"
}
install_pkgs() {
    # shellcheck disable=SC2086 # one word per package
    sudo apt-get install -y ${MISSING_PKGS} btrfs-progs
}
# Try the package lists already on the card first: apt-get update can take
# minutes on a slow connection. Refresh them only if the install fails or
# btrfs-progs is too old.
if [ -n "${MISSING_PKGS}" ] || ! btrfs_progs_ok; then
    if ! install_pkgs || ! btrfs_progs_ok; then
        progress 1 "Updating package lists"
        sudo apt-get update || fail 1 "apt-get update failed"
        install_pkgs || fail 1 "Failed to install:${MISSING_PKGS}"
    fi
fi
btrfs_progs_ok || fail 1 "btrfs-progs $(btrfs_progs_version) is older than ${MIN_BTRFS_PROGS}"

# --- Phase 1: Pre-flight checks ---
# nixos_migration_calc.py is the single source of truth for whether this
# system is ready to migrate (model, RAM, SD size + layout, free space,
# WiFi mode, supported display). A non-zero exit means all_ok is false.
progress 3 "Running pre-flight checks"

if ! python3 "${SCRIPT_DIR}/nixos_migration_calc.py" --json \
    --display-class "${DISPLAY_CLASS}" \
    --display-resolution "${DISPLAY_RESOLUTION}" \
    > /tmp/migration_checks.json 2>&1; then
    fail 1 "Pre-flight checks failed"
fi

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
    progress 10 "Downloading..."
    rm -f "${TARBALL}"

    if ! curl -L -f -o "${TARBALL}" \
        --progress-bar \
        "${MIGRATION_URL}" 2>&1 | tr '\r' '\n' | while IFS= read -r line; do
            if [[ "$line" =~ ([0-9]+)\.[0-9]% ]]; then
                dl_pct="${BASH_REMATCH[1]}"
                mapped_pct=$(( 10 + dl_pct * 50 / 100 ))
                progress "${mapped_pct}" "Downloading..."
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

# The initramfs converts the root in place and reads the tarball from the
# card, so the tarball does not have to fit in RAM.
TARBALL_MB=$((TARBALL_SIZE / 1048576))

progress 75 "Tarball: ${TARBALL_MB}MB"

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
for tool in e2fsck resize2fs btrfs btrfs-convert mkfs.vfat sfdisk zstd; do
    tool_path=$(command -v "${tool}" 2>/dev/null || true)
    if [ -z "${tool_path}" ]; then
        fail 5 "${tool} not found — install e2fsprogs btrfs-progs dosfstools util-linux zstd"
    fi
    copy_with_libs "${tool_path}" "${INITRAMFS_DIR}"
done

# glibc loads libgcc_s at run time for pthread_cancel, so ldd does not list
# it; btrfs-convert aborts without it.
LIBGCC_S=$(ldconfig -p 2>/dev/null | awk '/libgcc_s\.so\.1 / {print $NF; exit}')
[ -n "${LIBGCC_S}" ] || LIBGCC_S=$(find /lib /usr/lib -name libgcc_s.so.1 2>/dev/null | head -1)
[ -n "${LIBGCC_S}" ] || fail 5 "libgcc_s.so.1 not found"
mkdir -p "${INITRAMFS_DIR}$(dirname "${LIBGCC_S}")"
cp "${LIBGCC_S}" "${INITRAMFS_DIR}${LIBGCC_S}"

# GNU cp as gcp: the reflink copy into the PiFinder_data subvolume needs
# --reflink, which busybox cp does not have.
cp "$(command -v cp)" "${INITRAMFS_DIR}/bin/gcp"
copy_libs "$(command -v cp)" "${INITRAMFS_DIR}"

# btrfs kernel module and its dependencies, decompressed, numbered in load
# order. The init loads /lib/modules/btrfs/*.ko in that order.
# Modules must match the running kernel, which also boots the initramfs.
KVER=$(uname -r)
BTRFS_MOD_DIR="${INITRAMFS_DIR}/lib/modules/btrfs"
mkdir -p "${BTRFS_MOD_DIR}"
n=0
while read -r ko; do
    [ -f "${ko}" ] || continue
    n=$((n + 1))
    name=$(printf '%02d-%s' "${n}" "$(basename "${ko}" | sed 's/\.ko.*$//')")
    case "${ko}" in
        *.xz) xz -dc "${ko}" > "${BTRFS_MOD_DIR}/${name}.ko" ;;
        *.gz) gzip -dc "${ko}" > "${BTRFS_MOD_DIR}/${name}.ko" ;;
        *.zst) zstd -dc "${ko}" > "${BTRFS_MOD_DIR}/${name}.ko" ;;
        *) cp "${ko}" "${BTRFS_MOD_DIR}/${name}.ko" ;;
    esac
done < <(modprobe -S "${KVER}" --show-depends btrfs 2>/dev/null | awk '$1 == "insmod" {print $2}')
if [ "${n}" -eq 0 ] && ! grep -qw btrfs /proc/filesystems; then
    fail 5 "btrfs kernel module not found"
fi

# OLED progress display (static binary, no libs needed)
cp "${PROGRESS_BIN}" "${INITRAMFS_DIR}/bin/" 2>/dev/null || true

# SPI kernel modules — needed for OLED progress display
# Modules may be compressed (.ko.xz); decompress for insmod in initramfs
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

# Pre-stage NetworkManager keyfiles from the live wpa_supplicant.conf.
# Generating them here (with Python, on the full Debian system) rather
# than in the busybox initramfs lets us unit-test the conversion. The
# init script just copies these into the new rootfs.
WIFI_STAGED_DIR="${INITRAMFS_DIR}/wifi-staged"
WPA_CONF="/etc/wpa_supplicant/wpa_supplicant.conf"
if [ -f "${WPA_CONF}" ]; then
    PIFINDER_PYTHON_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
    PYTHONPATH="${PIFINDER_PYTHON_ROOT}" python3 \
        -m PiFinder.nixos_migration_wifi \
        --wpa-conf "${WPA_CONF}" \
        --out "${WIFI_STAGED_DIR}" \
        || fail 5 "WiFi keyfile generation failed"
fi

# Metadata: paths + sizes so init script knows where to find things
cat > "${INITRAMFS_DIR}/migration_meta" <<METAEOF
TARBALL_PATH=${TARBALL}
TARBALL_SIZE=${TARBALL_SIZE}
PIFINDER_DATA_PATH=${PIFINDER_HOME}/PiFinder_data
DISPLAY_CLASS=${DISPLAY_CLASS}
DISPLAY_RESOLUTION=${DISPLAY_RESOLUTION}
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
