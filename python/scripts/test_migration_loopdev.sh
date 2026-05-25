#!/bin/bash
# test_migration_loopdev.sh - Test migration against a real SD card image
#
# Copies a PiFinder SD card image, injects test data (fake NixOS tarball,
# backup, WiFi creds), then runs the full migration flow on the copy.
#
# Usage: sudo ./test_migration_loopdev.sh <image> [--keep]
#   image:  path to SD card image (e.g. pifinder-mr.img). COPIED, not modified.
#   --keep: don't clean up after test (inspect results manually)
#
# Requires: losetup, sfdisk, mkfs.ext4, mkfs.vfat, e2fsck, resize2fs
#
# Tests: partition shrink, staging area, format, tarball extraction,
#        PiFinder_data restore, WiFi migration, partition re-expansion

set -euo pipefail

if [ $# -lt 1 ] || [ "$1" = "--help" ]; then
    echo "Usage: sudo $0 <image> [--keep]"
    echo "  image: path to PiFinder SD card image (will be copied)"
    exit 1
fi

SOURCE_IMAGE="$1"; shift
KEEP=0
[ "${1:-}" = "--keep" ] && KEEP=1

[ ! -f "${SOURCE_IMAGE}" ] && { echo "Image not found: ${SOURCE_IMAGE}"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK_DIR="/tmp/migration_test_$$"
IMAGE="${WORK_DIR}/sd_card.img"
TARGET_SIZE_MB=32768  # extend to 32GB
# STAGING_SIZE_MB calculated dynamically after we know backup size

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[FAIL]${NC} $*"; }
pass()  { echo -e "${GREEN}[PASS]${NC} $*"; }

LOOP_DEV=""

cleanup() {
    local rc=$?
    if [ "${KEEP}" = "1" ] && [ "${rc}" = "0" ]; then
        warn "Keeping: ${WORK_DIR}"
        warn "Loop: ${LOOP_DEV:-none}"
        warn "Cleanup: sudo losetup -d ${LOOP_DEV:-?} && rm -rf ${WORK_DIR}"
        return "${rc}"
    fi
    info "Cleaning up..."
    # Unmount any mounted dirs (ignore glob expansion failures)
    umount "${WORK_DIR}"/mnt_* 2>/dev/null || true
    umount "${WORK_DIR}"/phase_* 2>/dev/null || true
    # Release loop device
    [ -n "${LOOP_DEV}" ] && losetup -d "${LOOP_DEV}" 2>/dev/null || true
    # Remove work dir
    rm -rf "${WORK_DIR}" 2>/dev/null || true
    [ "${rc}" != "0" ] && error "Test FAILED (exit ${rc})"
    return "${rc}"
}
trap cleanup EXIT

# -------------------------------------------------------------------
# Step 1: Copy image and set up loop device
# -------------------------------------------------------------------
mkdir -p "${WORK_DIR}"
info "Copying image ($(du -h "${SOURCE_IMAGE}" | cut -f1))..."
cp --sparse=always "${SOURCE_IMAGE}" "${IMAGE}"

CURRENT_SIZE=$(stat -c%s "${IMAGE}")
TARGET_SIZE=$(( TARGET_SIZE_MB * 1048576 ))
if [ "${CURRENT_SIZE}" -lt "${TARGET_SIZE}" ]; then
    info "Extending to ${TARGET_SIZE_MB}MB"
    truncate -s "${TARGET_SIZE_MB}M" "${IMAGE}"
fi

LOOP_DEV=$(losetup --find --show --partscan "${IMAGE}")
info "Loop device: ${LOOP_DEV}"
sleep 1
[ ! -b "${LOOP_DEV}p1" ] && { sleep 2; partprobe "${LOOP_DEV}"; sleep 1; }
[ ! -b "${LOOP_DEV}p1" ] && { error "${LOOP_DEV}p1 not found"; exit 1; }

# Read actual p2 start from the image
# sfdisk -d puts space between 'start=' and value, so use sed instead of awk
P2_START=$(sfdisk -d "${LOOP_DEV}" 2>/dev/null | grep 'p2' | sed 's/.*start=\s*//' | sed 's/,.*//')
[ -z "${P2_START}" ] && { error "Cannot read p2 start sector"; exit 1; }
info "p2 starts at sector ${P2_START}"

# Expand p2 to fill the (possibly extended) image
# sfdisk needs ", +" to expand - just "," preserves existing size
echo ", +" | sfdisk -N 2 "${LOOP_DEV}" --no-reread 2>/dev/null || true
partprobe "${LOOP_DEV}" 2>/dev/null || true
sleep 1
e2fsck -f -y "${LOOP_DEV}p2" 2>/dev/null || true
resize2fs "${LOOP_DEV}p2" 2>/dev/null || true

# -------------------------------------------------------------------
# Step 2: Inject test data onto the image
# -------------------------------------------------------------------
info "Mounting image..."
mkdir -p "${WORK_DIR}/mnt_boot" "${WORK_DIR}/mnt_root"
mount "${LOOP_DEV}p1" "${WORK_DIR}/mnt_boot"
mount "${LOOP_DEV}p2" "${WORK_DIR}/mnt_root"

# Add test markers to PiFinder_data (keep existing data from real image)
mkdir -p "${WORK_DIR}/mnt_root/home/pifinder/PiFinder_data"
echo '{"test": true}' > "${WORK_DIR}/mnt_root/home/pifinder/PiFinder_data/config.json"
dd if=/dev/urandom of="${WORK_DIR}/mnt_root/home/pifinder/PiFinder_data/observations.db" bs=1K count=32 2>/dev/null

# Replace wpa_supplicant.conf with known test data
mkdir -p "${WORK_DIR}/mnt_root/etc/wpa_supplicant"
cat > "${WORK_DIR}/mnt_root/etc/wpa_supplicant/wpa_supplicant.conf" <<'WPAEOF'
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US

network={
	ssid="HomeNetwork"
	psk="password123"
	key_mgmt=WPA-PSK
}

network={
	ssid="Coffee Shop WiFi"
	psk="cafelatte"
	key_mgmt=WPA-PSK
}

network={
	ssid="OpenNetwork"
	key_mgmt=NONE
}
WPAEOF

# Build fake NixOS tarball
info "Creating fake NixOS tarball..."
TARBALL_STAGING="${WORK_DIR}/tarball_staging"
mkdir -p "${TARBALL_STAGING}/boot" "${TARBALL_STAGING}/rootfs"

echo "# NixOS extlinux.conf" > "${TARBALL_STAGING}/boot/extlinux.conf"
dd if=/dev/urandom of="${TARBALL_STAGING}/boot/Image" bs=1K count=128 2>/dev/null

mkdir -p "${TARBALL_STAGING}/rootfs/nix/store"
mkdir -p "${TARBALL_STAGING}/rootfs/etc/NetworkManager/system-connections"
mkdir -p "${TARBALL_STAGING}/rootfs/home/pifinder"
echo "NixOS rootfs marker" > "${TARBALL_STAGING}/rootfs/etc/NIXOS"
dd if=/dev/urandom of="${TARBALL_STAGING}/rootfs/nix/store/fakepkg" bs=1K count=256 2>/dev/null
echo '{"version": "2.5.0"}' > "${TARBALL_STAGING}/manifest.json"

tar czf "${WORK_DIR}/mnt_root/home/pifinder/pifinder-nixos-migration.tar.gz" \
    -C "${TARBALL_STAGING}" boot rootfs manifest.json

TARBALL_SIZE=$(stat -c%s "${WORK_DIR}/mnt_root/home/pifinder/pifinder-nixos-migration.tar.gz")
PIFINDER_DATA_PATH="/home/pifinder/PiFinder_data"

# Estimate backup size to calculate staging area
# Images compress poorly (JPEG/PNG already compressed), so use conservative 85%
PIFINDER_DATA_ON_ROOT="${WORK_DIR}/mnt_root${PIFINDER_DATA_PATH}"
DATA_SIZE_RAW=$(du -sb "${PIFINDER_DATA_ON_ROOT}" --exclude='captures' --exclude='screenshots' 2>/dev/null | cut -f1)
BACKUP_EST_BYTES=$(( DATA_SIZE_RAW * 85 / 100 ))  # Conservative: images don't compress well
STAGING_NEED_BYTES=$(( TARBALL_SIZE + BACKUP_EST_BYTES + 209715200 ))  # +200MB margin
STAGING_SIZE_MB=$(( (STAGING_NEED_BYTES / 1048576) + 1 ))
# Minimum 1GB staging
[ "${STAGING_SIZE_MB}" -lt 1024 ] && STAGING_SIZE_MB=1024
info "Estimated staging need: ${STAGING_SIZE_MB}MB (data ${DATA_SIZE_RAW}, backup est ${BACKUP_EST_BYTES})"

# Migration flag on boot
touch "${WORK_DIR}/mnt_boot/nixos_migration"

umount "${WORK_DIR}/mnt_boot"
umount "${WORK_DIR}/mnt_root"

info "Injected: tarball ${TARBALL_SIZE} bytes"

# -------------------------------------------------------------------
# Step 3: Write migration metadata
# -------------------------------------------------------------------
cat > /tmp/test_migration_meta_$$ <<METAEOF
TARBALL_PATH=/home/pifinder/pifinder-nixos-migration.tar.gz
PIFINDER_DATA_PATH=${PIFINDER_DATA_PATH}
TARBALL_SIZE=${TARBALL_SIZE}
STAGING_SIZE_MB=${STAGING_SIZE_MB}
METAEOF

# -------------------------------------------------------------------
# Step 4: Run the migration
# -------------------------------------------------------------------
info "========================================"
info "Running migration..."
info "========================================"

# Source metadata
. /tmp/test_migration_meta_$$

SD_DEV="${LOOP_DEV}"
BOOT_DEV="${LOOP_DEV}p1"
ROOT_DEV="${LOOP_DEV}p2"
MOUNT_ROOT="${WORK_DIR}/phase_root"
MOUNT_NEW="${WORK_DIR}/phase_new"
MOUNT_BOOT="${WORK_DIR}/phase_boot"

show() { echo -e "  ${GREEN}[${1}%]${NC} ${2}"; }
fail() { echo -e "  ${RED}FAIL: $1${NC}"; exit 1; }

# --- Check root filesystem ---
show 5 "e2fsck"
e2fsck -f -y "${ROOT_DEV}" || fail "e2fsck"

mkdir -p "${MOUNT_ROOT}"
mount -t ext4 -o ro "${ROOT_DEV}" "${MOUNT_ROOT}" || fail "mount root"

TARBALL_ON_ROOT="${MOUNT_ROOT}${TARBALL_PATH}"
PIFINDER_DATA_ON_ROOT="${MOUNT_ROOT}${PIFINDER_DATA_PATH}"

[ ! -f "${TARBALL_ON_ROOT}" ] && { umount "${MOUNT_ROOT}"; fail "tarball not found"; }
[ ! -d "${PIFINDER_DATA_ON_ROOT}" ] && { umount "${MOUNT_ROOT}"; fail "PiFinder_data not found"; }

# Save WiFi creds
WPA_FILE="${MOUNT_ROOT}/etc/wpa_supplicant/wpa_supplicant.conf"
mkdir -p /tmp/wifi_test_$$
[ -f "${WPA_FILE}" ] && cp "${WPA_FILE}" "/tmp/wifi_test_$$/wpa_supplicant.conf"

umount "${MOUNT_ROOT}"

# --- Shrink root FS + partition ---
show 12 "Shrinking root FS"

SD_BYTES=$(blockdev --getsize64 "${SD_DEV}")
SD_SECTORS=$(blockdev --getsz "${SD_DEV}")

STAGING_SECTORS=$(( STAGING_SIZE_MB * 1024 * 1024 / 512 ))
P2_CURRENT_SECTORS=$(( SD_SECTORS - P2_START ))
P2_NEW_SECTORS=$(( P2_CURRENT_SECTORS - STAGING_SECTORS ))
[ "${P2_NEW_SECTORS}" -le 0 ] && fail "SD too small for staging"

BLOCK_SIZE=4096
P2_NEW_BLOCKS=$(( P2_NEW_SECTORS * 512 / BLOCK_SIZE ))

resize2fs "${ROOT_DEV}" "${P2_NEW_BLOCKS}" || fail "resize2fs shrink"

show 18 "Shrinking partition table"
echo "${P2_START}, ${P2_NEW_SECTORS}" | sfdisk -N 2 "${SD_DEV}" --no-reread 2>/dev/null || fail "sfdisk shrink"
partprobe "${SD_DEV}" 2>/dev/null || true
sleep 1

STAGING_START_BYTE=$(( (P2_START + P2_NEW_SECTORS) * 512 ))
show 20 "Staging area at byte ${STAGING_START_BYTE}"

# --- Copy tarball + stream backup to staging area ---
show 22 "Mounting shrunk root"
mount -t ext4 -o ro "${ROOT_DEV}" "${MOUNT_ROOT}" || fail "mount shrunk root"

TARBALL_ON_ROOT="${MOUNT_ROOT}${TARBALL_PATH}"
PIFINDER_DATA_ON_ROOT="${MOUNT_ROOT}${PIFINDER_DATA_PATH}"

# Layout: header (4K) | tarball | backup
TARBALL_ALIGNED=$(( (TARBALL_SIZE + 4095) / 4096 * 4096 ))
TARBALL_STAGING_BYTE=$(( STAGING_START_BYTE + 4096 ))
BACKUP_STAGING_BYTE=$(( TARBALL_STAGING_BYTE + TARBALL_ALIGNED ))

show 25 "Copying tarball to staging"
dd if="${TARBALL_ON_ROOT}" of="${SD_DEV}" bs=4096 \
    seek=$(( TARBALL_STAGING_BYTE / 4096 )) conv=notrunc 2>/dev/null || fail "tarball stage"

show 35 "Creating backup"
# Create backup in tmpfs (RAM) then copy to staging
# Exclude captures and screenshots (user-generated ephemeral data)
BACKUP_TMP="/tmp/pifinder_backup_$$.tar.gz"
tar czf "${BACKUP_TMP}" -C "$(dirname "${PIFINDER_DATA_ON_ROOT}")" \
    --exclude='PiFinder_data/captures' \
    --exclude='PiFinder_data/screenshots' \
    "$(basename "${PIFINDER_DATA_ON_ROOT}")" 2>/dev/null || fail "backup create"

BACKUP_SIZE=$(stat -c%s "${BACKUP_TMP}")
show 37 "Backup created (${BACKUP_SIZE} bytes)"

show 38 "Copying backup to staging"
dd if="${BACKUP_TMP}" of="${SD_DEV}" bs=4096 \
    seek=$(( BACKUP_STAGING_BYTE / 4096 )) conv=notrunc 2>/dev/null || fail "backup stage"
rm -f "${BACKUP_TMP}"
show 40 "Backup staged"

umount "${MOUNT_ROOT}"

# Write header with actual backup size
HEADER_FILE="/tmp/staging_header_$$"
dd if=/dev/zero of="${HEADER_FILE}" bs=4096 count=1 2>/dev/null
printf "PFMIGRATE1\ntarball_size=%s\nbackup_size=%s\n" "${TARBALL_SIZE}" "${BACKUP_SIZE}" | \
    dd of="${HEADER_FILE}" conv=notrunc 2>/dev/null
dd if="${HEADER_FILE}" of="${SD_DEV}" bs=4096 seek=$(( STAGING_START_BYTE / 4096 )) conv=notrunc 2>/dev/null

# Verify header
MAGIC=$(dd if="${SD_DEV}" bs=4096 skip=$(( STAGING_START_BYTE / 4096 )) count=1 2>/dev/null | head -1)
[ "${MAGIC}" != "PFMIGRATE1" ] && fail "header verify failed (got: ${MAGIC})"

show 42 "Staging verified"

# === POINT OF NO RETURN ===
show 45 "FORMATTING"

mkfs.vfat -F 32 -n FIRMWARE "${BOOT_DEV}" || fail "mkfs.vfat"
show 50 "Format root"
mkfs.ext4 -F -L NIXOS_SD "${ROOT_DEV}" || fail "mkfs.ext4"
show 55 "Formatted"

# --- Extract NixOS ---
show 57 "Extracting tarball"
mkdir -p "${MOUNT_NEW}"
mount -t ext4 "${ROOT_DEV}" "${MOUNT_NEW}" || fail "mount new root"

TARBALL_SKIP_BLOCKS=$(( TARBALL_STAGING_BYTE / 4096 ))
TARBALL_COUNT_BLOCKS=$(( (TARBALL_SIZE + 4095) / 4096 ))

dd if="${SD_DEV}" bs=4096 skip="${TARBALL_SKIP_BLOCKS}" count="${TARBALL_COUNT_BLOCKS}" 2>/dev/null | \
    gunzip | tar xf - -C "${MOUNT_NEW}" || fail "extract"

show 70 "Extracted"

# Move boot/ to boot partition
mkdir -p "${MOUNT_BOOT}"
mount -t vfat "${BOOT_DEV}" "${MOUNT_BOOT}" || fail "mount boot"

if [ -d "${MOUNT_NEW}/boot" ]; then
    cp -a "${MOUNT_NEW}/boot/." "${MOUNT_BOOT}/"
    rm -rf "${MOUNT_NEW}/boot"
fi

# Move rootfs/ contents up
if [ -d "${MOUNT_NEW}/rootfs" ]; then
    # Use find to avoid glob expansion issues with empty dirs
    find "${MOUNT_NEW}/rootfs" -mindepth 1 -maxdepth 1 -exec mv {} "${MOUNT_NEW}/" \; 2>/dev/null || true
    rmdir "${MOUNT_NEW}/rootfs" 2>/dev/null || true
fi
rm -f "${MOUNT_NEW}/manifest.json"

show 78 "Layout done"

# --- Restore backup ---
show 80 "Restoring user data"
mkdir -p "${MOUNT_NEW}/home/pifinder"

BACKUP_SKIP_BLOCKS=$(( BACKUP_STAGING_BYTE / 4096 ))
BACKUP_COUNT_BLOCKS=$(( (BACKUP_SIZE + 4095) / 4096 ))

dd if="${SD_DEV}" bs=4096 skip="${BACKUP_SKIP_BLOCKS}" count="${BACKUP_COUNT_BLOCKS}" 2>/dev/null | \
    gunzip | tar xf - -C "${MOUNT_NEW}/home/pifinder/" || fail "restore backup"

show 85 "Data restored"

# --- WiFi migration ---
show 88 "Migrating WiFi"
if [ -f "/tmp/wifi_test_$$/wpa_supplicant.conf" ]; then
    NM_DIR="${MOUNT_NEW}/etc/NetworkManager/system-connections"
    mkdir -p "${NM_DIR}"

    SSID="" PSK="" IN_NET=0
    while IFS= read -r line; do
        line=$(echo "${line}" | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//')
        case "${line}" in
            network=*) IN_NET=1; SSID=""; PSK="" ;;
            "}")
                if [ "${IN_NET}" = "1" ] && [ -n "${SSID}" ]; then
                    FN=$(echo "${SSID}" | sed 's/[^a-zA-Z0-9_-]/_/g')
                    CONN="${NM_DIR}/${FN}.nmconnection"
                    {
                        printf "[connection]\nid=%s\ntype=wifi\nautoconnect=true\n\n" "${SSID}"
                        printf "[wifi]\nssid=%s\nmode=infrastructure\n\n" "${SSID}"
                    } > "${CONN}"
                    if [ -n "${PSK}" ]; then
                        printf "[wifi-security]\nkey-mgmt=wpa-psk\npsk=%s\n\n" "${PSK}" >> "${CONN}"
                    fi
                    printf "[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=auto\n" >> "${CONN}"
                    chmod 600 "${CONN}"
                fi
                IN_NET=0 ;;
            ssid=*)  [ "${IN_NET}" = "1" ] && SSID=$(echo "${line}" | sed 's/^ssid="//;s/"$//') ;;
            psk=*)   [ "${IN_NET}" = "1" ] && PSK=$(echo "${line}" | sed 's/^psk="//;s/"$//') ;;
        esac
    done < "/tmp/wifi_test_$$/wpa_supplicant.conf"
fi

show 92 "WiFi done"

# --- Expand partition back ---
show 95 "Expanding root"
umount "${MOUNT_NEW}"
umount "${MOUNT_BOOT}" 2>/dev/null || true
# Expand partition to fill card
echo ", +" | sfdisk -N 2 "${SD_DEV}" 2>/dev/null || true
# Force kernel to re-read partition table
partprobe "${SD_DEV}" 2>/dev/null || true
losetup -c "${SD_DEV}" 2>/dev/null || true  # Update loop device
sleep 2
# Expand filesystem (e2fsck required before resize2fs on loop devices)
e2fsck -f -y "${ROOT_DEV}" 2>/dev/null || true
resize2fs "${ROOT_DEV}" 2>/dev/null || true

sync
rm -rf "/tmp/wifi_test_$$" "/tmp/staging_header_$$" "/tmp/test_migration_meta_$$"

show 100 "Migration complete!"

# -------------------------------------------------------------------
# Step 5: Verify results
# -------------------------------------------------------------------
echo ""
info "========================================"
info "Verifying..."
info "========================================"

ERRORS=0

mkdir -p "${WORK_DIR}/mnt_boot" "${WORK_DIR}/mnt_root"
mount "${LOOP_DEV}p1" "${WORK_DIR}/mnt_boot"
mount "${LOOP_DEV}p2" "${WORK_DIR}/mnt_root"

check() {
    local desc="$1" cond="$2"
    if eval "${cond}"; then
        pass "${desc}"
    else
        error "${desc}"
        ERRORS=$((ERRORS + 1))
    fi
}

check "Boot label = FIRMWARE" \
    '[ "$(blkid -s LABEL -o value "${LOOP_DEV}p1")" = "FIRMWARE" ]'

check "Root label = NIXOS_SD" \
    '[ "$(blkid -s LABEL -o value "${LOOP_DEV}p2")" = "NIXOS_SD" ]'

check "NixOS marker exists" \
    '[ -f "${WORK_DIR}/mnt_root/etc/NIXOS" ]'

check "Nix store dir exists" \
    '[ -d "${WORK_DIR}/mnt_root/nix/store" ]'

check "Boot: extlinux.conf" \
    '[ -f "${WORK_DIR}/mnt_boot/extlinux.conf" ]'

check "Old boot files gone" \
    '[ ! -f "${WORK_DIR}/mnt_boot/config.txt" ]'

check "PiFinder_data/config.json restored" \
    '[ -f "${WORK_DIR}/mnt_root/home/pifinder/PiFinder_data/config.json" ]'

check "PiFinder_data/observations.db restored" \
    '[ -f "${WORK_DIR}/mnt_root/home/pifinder/PiFinder_data/observations.db" ]'

NM_DIR="${WORK_DIR}/mnt_root/etc/NetworkManager/system-connections"

check "WiFi: HomeNetwork migrated" \
    '[ -f "${NM_DIR}/HomeNetwork.nmconnection" ]'

check "WiFi: HomeNetwork PSK correct" \
    'grep -q "psk=password123" "${NM_DIR}/HomeNetwork.nmconnection" 2>/dev/null'

check "WiFi: Coffee_Shop_WiFi migrated" \
    '[ -f "${NM_DIR}/Coffee_Shop_WiFi.nmconnection" ]'

check "WiFi: OpenNetwork migrated" \
    '[ -f "${NM_DIR}/OpenNetwork.nmconnection" ]'

check "WiFi: OpenNetwork has no PSK" \
    '! grep -q "wifi-security" "${NM_DIR}/OpenNetwork.nmconnection" 2>/dev/null'

for f in "${NM_DIR}"/*.nmconnection; do
    [ ! -f "$f" ] && continue
    check "WiFi: $(basename "$f") perms=600" \
        '[ "$(stat -c%a "'"$f"'")" = "600" ]'
done

ROOT_BLOCKS=$(dumpe2fs -h "${LOOP_DEV}p2" 2>/dev/null | awk '/Block count/ {print $3}')
ROOT_BSIZE=$(dumpe2fs -h "${LOOP_DEV}p2" 2>/dev/null | awk '/Block size/ {print $3}')
ROOT_GB=$(( ROOT_BLOCKS * ROOT_BSIZE / 1073741824 ))
check "Root FS expanded (${ROOT_GB}GB >= 28GB)" \
    '[ "${ROOT_GB}" -ge 28 ]'

umount "${WORK_DIR}/mnt_boot"
umount "${WORK_DIR}/mnt_root"

echo ""
echo "========================================"
if [ "${ERRORS}" = "0" ]; then
    pass "All ${ERRORS:-0} checks passed!"
else
    error "${ERRORS} check(s) failed"
fi
echo "========================================"

exit "${ERRORS}"
