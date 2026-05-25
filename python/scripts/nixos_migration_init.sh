#!/bin/busybox sh
# nixos_migration_init.sh - Initramfs init for NixOS migration
#
# Runs entirely from RAM. Strategy:
#   1. Save WiFi credentials and user backup to RAM
#   2. Copy tarball to RAM, unmount old root
#   3. Format both partitions
#   4. Extract tarball (boot → p1, rootfs → p2)
#   5. Restore WiFi + user data, expand partition
#   6. Reboot into NixOS

set -e

/bin/busybox --install -s /bin 2>/dev/null || true

mount -t proc proc /proc 2>/dev/null || true
mount -t sysfs sysfs /sys 2>/dev/null || true
mount -t devtmpfs devtmpfs /dev 2>/dev/null || true
mount -t tmpfs tmpfs /tmp 2>/dev/null || true

# Load SPI modules for OLED progress display
if [ -f /lib/modules/spi-bcm2835.ko ]; then
    insmod /lib/modules/spi-bcm2835.ko 2>/dev/null || true
    insmod /lib/modules/spidev.ko 2>/dev/null || true
    sleep 0.5
fi

# Shared lib path for dynamically linked tools (e2fsck, mkfs, etc.)
export LD_LIBRARY_PATH=/lib:/usr/lib:/lib/aarch64-linux-gnu:/usr/lib/aarch64-linux-gnu

BOOT_DEV="/dev/mmcblk0p1"
ROOT_DEV="/dev/mmcblk0p2"
SD_DEV="/dev/mmcblk0"
MOUNT_ROOT="/mnt/root"
MOUNT_NEW="/mnt/new"
MOUNT_BOOT="/mnt/boot"
PROGRESS="/bin/migration_progress"

STAGE_NUM=0
STAGE_TOTAL=22

show() {
    local pct="$1"
    local msg="$2"
    STAGE_NUM=$((STAGE_NUM + 1))
    echo "[${pct}%] ${msg}" > /dev/console 2>/dev/null || true
    echo "[${pct}%] ${msg}"
    [ -x "${PROGRESS}" ] && "${PROGRESS}" "${pct}" "${STAGE_NUM}" "${STAGE_TOTAL}" "${msg}" 2>/dev/null || true
}

fail() {
    [ -x "${PROGRESS}" ] && "${PROGRESS}" 0 0 0 "FAILED: $1" 2>/dev/null || true
    echo "[FAILED] $1"
    echo "MIGRATION FAILED: $1" > /dev/console 2>/dev/null || true
    echo "Dropping to shell for debugging..."
    exec /bin/sh
}

show 28 "Migrating..."

# Wait for SD card device to appear
n=0
while [ ! -b "${BOOT_DEV}" ] && [ "${n}" -lt 30 ]; do
    sleep 1
    n=$((n + 1))
done
[ ! -b "${BOOT_DEV}" ] && fail "SD card not found after 30s: ${BOOT_DEV}"

show 30 "Initramfs started"

# -------------------------------------------------------------------
# Phase 1: Validate
# -------------------------------------------------------------------

# Check migration flag on boot partition
mkdir -p /mnt/bootchk
mount -t vfat -o ro "${BOOT_DEV}" /mnt/bootchk || fail "Cannot mount boot"
if [ ! -f /mnt/bootchk/nixos_migration ]; then
    umount /mnt/bootchk
    fail "No migration flag — aborting"
fi
umount /mnt/bootchk

# Read metadata written by pre-migration script
if [ ! -f /migration_meta ]; then
    fail "migration_meta not found in initramfs"
fi
. /migration_meta
# Now we have: TARBALL_PATH, TARBALL_SIZE, PIFINDER_DATA_PATH

# RAM check: tarball + backup + overhead must fit
MEM_KB=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
MEM_MB=$((MEM_KB / 1024))
TARBALL_SIZE_MB=$((TARBALL_SIZE / 1048576))
NEEDED_MB=$((TARBALL_SIZE_MB + 150))  # tarball + backup + overhead
[ "${MEM_MB}" -lt "${NEEDED_MB}" ] && fail "Insufficient RAM: ${MEM_MB}MB available, need ${NEEDED_MB}MB"

show 31 "Validated (${MEM_MB}MB free)"

# -------------------------------------------------------------------
# Phase 2: Save WiFi credentials to RAM
# -------------------------------------------------------------------

show 33 "Saving WiFi to RAM"

mkdir -p "${MOUNT_ROOT}"
mount -t ext4 -o ro "${ROOT_DEV}" "${MOUNT_ROOT}" || fail "Cannot mount root"

mkdir -p /tmp/wifi
WPA_FILE="${MOUNT_ROOT}/etc/wpa_supplicant/wpa_supplicant.conf"
if [ -f "${WPA_FILE}" ]; then
    cp "${WPA_FILE}" /tmp/wifi/wpa_supplicant.conf
fi

NM_SRC="${MOUNT_ROOT}/etc/NetworkManager/system-connections"
if [ -d "${NM_SRC}" ]; then
    mkdir -p /tmp/wifi/nm-connections
    cp -a "${NM_SRC}/." /tmp/wifi/nm-connections/ 2>/dev/null || true
fi

# -------------------------------------------------------------------
# Phase 3: Create user backup in RAM
# -------------------------------------------------------------------

show 35 "Creating backup"

PIFINDER_DATA_ON_ROOT="${MOUNT_ROOT}${PIFINDER_DATA_PATH}"
BACKUP_STAGE="/tmp/backup_stage/PiFinder_data"
rm -rf /tmp/backup_stage
mkdir -p "${BACKUP_STAGE}"

if [ -d "${PIFINDER_DATA_ON_ROOT}" ]; then
    # Copy root-level files (observations.db, configs, etc.)
    for f in "${PIFINDER_DATA_ON_ROOT}"/*; do
        [ -f "$f" ] && cp "$f" "${BACKUP_STAGE}/" 2>/dev/null || true
    done

    # Truncate log to last 1000 lines
    if [ -f "${BACKUP_STAGE}/pifinder.log" ]; then
        tail -n 1000 "${BACKUP_STAGE}/pifinder.log" > "${BACKUP_STAGE}/pifinder.log.tmp"
        mv "${BACKUP_STAGE}/pifinder.log.tmp" "${BACKUP_STAGE}/pifinder.log"
    fi

    # Copy obslists directory
    if [ -d "${PIFINDER_DATA_ON_ROOT}/obslists" ]; then
        cp -a "${PIFINDER_DATA_ON_ROOT}/obslists" "${BACKUP_STAGE}/obslists"
    fi
fi

show 38 "Backup created"

# -------------------------------------------------------------------
# Phase 4: Copy tarball to RAM, unmount old root
# -------------------------------------------------------------------

show 40 "Loading tarball to RAM"

TARBALL_ON_ROOT="${MOUNT_ROOT}${TARBALL_PATH}"
[ ! -f "${TARBALL_ON_ROOT}" ] && { umount "${MOUNT_ROOT}"; fail "Tarball not found: ${TARBALL_PATH}"; }

cp "${TARBALL_ON_ROOT}" /tmp/migration.tar.zst || fail "Failed to copy tarball to RAM"
umount "${MOUNT_ROOT}"

show 48 "Tarball loaded to RAM"

# -------------------------------------------------------------------
# Phase 5: Expand + format partitions
# -------------------------------------------------------------------

show 49 "Expanding partition"

# Expand partition 2 BEFORE formatting — sfdisk rewrites the MBR and
# blockdev --rereadpt can corrupt a written FAT partition if done after.
echo ", +" | sfdisk -N 2 "${SD_DEV}" --no-reread 2>/dev/null || true
blockdev --rereadpt "${SD_DEV}" 2>/dev/null || true
sleep 1

show 50 "Formatting boot"

mkfs.vfat -F 32 -n FIRMWARE "${BOOT_DEV}" || fail "mkfs.vfat failed"

show 52 "Formatting root"

mkfs.ext4 -F -L NIXOS_SD "${ROOT_DEV}" || fail "mkfs.ext4 failed"

# -------------------------------------------------------------------
# Phase 6: Extract tarball
# -------------------------------------------------------------------

show 55 "Extracting NixOS"

mkdir -p "${MOUNT_NEW}"
mount -t ext4 "${ROOT_DEV}" "${MOUNT_NEW}" || fail "Cannot mount new root"

# Extract tarball directly to SD card (ext4 has plenty of space, tmpfs does not)
zstd -d < /tmp/migration.tar.zst | tar xf - -C "${MOUNT_NEW}" || fail "Tarball extraction failed"
rm -f /tmp/migration.tar.zst

show 60 "Moving rootfs"

# Move rootfs/ contents up to partition root (same-fs rename, fast)
cd "${MOUNT_NEW}/rootfs"
for item in * .[!.]* ..?*; do
    [ -e "$item" ] || continue
    mv "$item" "${MOUNT_NEW}/"
done
cd /
rmdir "${MOUNT_NEW}/rootfs"

show 66 "Copying boot"

mkdir -p "${MOUNT_BOOT}"
mount -t vfat "${BOOT_DEV}" "${MOUNT_BOOT}" || fail "Cannot mount boot"

# Copy boot files to FAT partition
cd "${MOUNT_NEW}/boot"
for item in *; do
    [ -e "$item" ] || continue
    if [ -d "$item" ]; then
        cp -r "$item" "${MOUNT_BOOT}/$item"
    else
        cp "$item" "${MOUNT_BOOT}/$item"
    fi
done
cd /
sync

# Verify critical boot files landed
if [ ! -f "${MOUNT_BOOT}/extlinux/extlinux.conf" ]; then
    echo "Boot partition contents:" >&2
    ls -lR "${MOUNT_BOOT}" >&2
    fail "extlinux.conf missing from boot partition after copy"
fi

# Keep boot/ on ext4 — U-Boot reads extlinux.conf from mmc 0:2 (ext4 root)
# FAT partition only needs RPi firmware files (config.txt, u-boot, DTBs)

# -------------------------------------------------------------------
# Phase 7: Migrate WiFi
# -------------------------------------------------------------------

show 70 "Migrating WiFi"

NM_DIR="${MOUNT_NEW}/etc/NetworkManager/system-connections"
mkdir -p "${NM_DIR}"

if [ -f /tmp/wifi/wpa_supplicant.conf ]; then
    SSID=""
    PSK=""
    IN_NET=0

    while IFS= read -r line; do
        line=$(echo "${line}" | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//')

        case "${line}" in
            network=*)
                IN_NET=1
                SSID=""
                PSK=""
                ;;
            "}")
                if [ "${IN_NET}" = "1" ] && [ -n "${SSID}" ]; then
                    NM_FILE="${NM_DIR}/${SSID}.nmconnection"

                    if [ -n "${PSK}" ]; then
                        cat > "${NM_FILE}" <<NMEOF
[connection]
id=${SSID}
type=wifi
autoconnect=true

[wifi]
mode=infrastructure
ssid=${SSID}

[wifi-security]
key-mgmt=wpa-psk
psk=${PSK}

[ipv4]
method=auto

[ipv6]
method=auto
NMEOF
                    else
                        cat > "${NM_FILE}" <<NMEOF
[connection]
id=${SSID}
type=wifi
autoconnect=true

[wifi]
mode=infrastructure
ssid=${SSID}

[ipv4]
method=auto

[ipv6]
method=auto
NMEOF
                    fi

                    chmod 600 "${NM_FILE}"
                fi
                IN_NET=0
                ;;
            ssid=*)
                [ "${IN_NET}" = "1" ] && SSID=$(echo "${line}" | sed 's/^ssid="//' | sed 's/"$//')
                ;;
            psk=*)
                [ "${IN_NET}" = "1" ] && PSK=$(echo "${line}" | sed 's/^psk="//' | sed 's/"$//')
                ;;
        esac
    done < /tmp/wifi/wpa_supplicant.conf
fi

if [ -d /tmp/wifi/nm-connections ]; then
    cp -a /tmp/wifi/nm-connections/. "${NM_DIR}/" 2>/dev/null || true
fi

sync

show 74 "WiFi migrated"

# -------------------------------------------------------------------
# Phase 8: Restore user data
# -------------------------------------------------------------------

show 76 "Restoring user data"

mkdir -p "${MOUNT_NEW}/home/pifinder"

if [ -d /tmp/backup_stage/PiFinder_data ]; then
    cp -a /tmp/backup_stage/PiFinder_data "${MOUNT_NEW}/home/pifinder/"
fi

# pifinder user: UID 1000, GID 100 (users) on NixOS
chown -R 1000:100 "${MOUNT_NEW}/home/pifinder" 2>/dev/null || true

show 80 "User data restored"

# -------------------------------------------------------------------
# Phase 9: Expand partition and finalize
# -------------------------------------------------------------------

umount "${MOUNT_BOOT}" 2>/dev/null || true
umount "${MOUNT_NEW}" 2>/dev/null || true

show 82 "Resizing filesystem"

e2fsck -f -y "${ROOT_DEV}" 2>/dev/null || true
resize2fs "${ROOT_DEV}" 2>/dev/null || true

show 92 "Syncing"
sync

# Final verification: remount boot partition and confirm extlinux.conf survived
show 95 "Verifying boot"
mkdir -p /mnt/bootchk
mount -t vfat -o ro "${BOOT_DEV}" /mnt/bootchk || fail "Cannot remount boot for verification"
if [ ! -f /mnt/bootchk/extlinux/extlinux.conf ]; then
    ls -lR /mnt/bootchk > /dev/console 2>&1 || true
    umount /mnt/bootchk 2>/dev/null || true
    fail "extlinux.conf missing from boot partition before reboot"
fi
umount /mnt/bootchk

show 100 "Complete"
sleep 3

echo "Rebooting into NixOS..." > /dev/console 2>/dev/null || true
reboot -f
