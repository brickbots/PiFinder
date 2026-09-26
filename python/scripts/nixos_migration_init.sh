#!/bin/busybox sh
# nixos_migration_init.sh - Initramfs init for NixOS migration
#
# Strategy (ADR 0039):
#   1. Save WiFi credentials and the camera type to RAM
#   2. Grow partition 2 and its ext4, then convert it to btrfs in place
#      (btrfs-convert keeps every file, the catalog images included)
#   3. Move PiFinder_data into its own subvolume, remove Pi OS
#   4. Extract the tarball (boot -> p1 FAT, rootfs -> p2 btrfs)
#   5. Restore WiFi, write the camera type, reboot into NixOS

set -e

# The OLED progress display is driven through a pipe (fd 3). If that process
# ever dies, a write must not take a fatal SIGPIPE and abort the migration —
# the display is best-effort, the migration is not.
trap '' PIPE

/bin/busybox --install -s /bin 2>/dev/null || true

mount -t proc proc /proc 2>/dev/null || true
mount -t sysfs sysfs /sys 2>/dev/null || true
mount -t devtmpfs devtmpfs /dev 2>/dev/null || true
# size=90%: the default tmpfs cap (50% of RAM) is smaller than the tarball on
# 2GB boards even when total RAM suffices — the explicit MemAvailable checks
# below are the real guard, the cap must never trip first.
mount -t tmpfs -o size=90% tmpfs /tmp 2>/dev/null || true

# Load SPI modules for OLED progress display
if [ -f /lib/modules/spi-bcm2835.ko ]; then
    insmod /lib/modules/spi-bcm2835.ko 2>/dev/null || true
    insmod /lib/modules/spidev.ko 2>/dev/null || true
    sleep 0.5
fi

# Shared lib path for dynamically linked tools (e2fsck, btrfs-convert, etc.)
export LD_LIBRARY_PATH=/lib:/usr/lib:/lib/aarch64-linux-gnu:/usr/lib/aarch64-linux-gnu

BOOT_DEV="/dev/mmcblk0p1"
ROOT_DEV="/dev/mmcblk0p2"
SD_DEV="/dev/mmcblk0"
MOUNT_ROOT="/mnt/root"
MOUNT_NEW="/mnt/new"
MOUNT_BOOT="/mnt/boot"
PROGRESS="/bin/migration_progress"

STAGE_NUM=0
STAGE_TOTAL=19
PROGRESS_FIFO="/tmp/migration_progress.fifo"
PROGRESS_READY=0

# Drive the OLED with a single long-lived process. It initialises the panel
# once and redraws in place from stdin, so the display never resets to black
# between stages (a fresh process per stage would re-assert the panel's RST
# line and blank it). fd 3 is the persistent writer; keeping it open stops the
# server seeing EOF until the migration is done.
if [ -x "${PROGRESS}" ]; then
    rm -f "${PROGRESS_FIFO}"
    mkfifo "${PROGRESS_FIFO}" 2>/dev/null || true
    "${PROGRESS}" --serve < "${PROGRESS_FIFO}" >/dev/null 2>&1 &
    exec 3>"${PROGRESS_FIFO}"
    PROGRESS_READY=1
fi

show() {
    local pct="$1"
    local msg="$2"
    STAGE_NUM=$((STAGE_NUM + 1))
    echo "[${pct}%] ${msg}" > /dev/console 2>/dev/null || true
    echo "[${pct}%] ${msg}"
    if [ "${PROGRESS_READY}" -eq 1 ]; then
        echo "${pct} ${STAGE_NUM} ${STAGE_TOTAL} ${msg}" >&3 2>/dev/null || true
    fi
}

# Update the display within the current step (no new step number), for
# long steps that must visibly move.
show_update() {
    if [ "${PROGRESS_READY}" -eq 1 ]; then
        echo "$1 ${STAGE_NUM} ${STAGE_TOTAL} $2" >&3 2>/dev/null || true
    fi
}

# Set to 1 immediately before the first destructive step (formatting). While
# it is 0, a failure can and must send the device back to the old OS.
DESTRUCTIVE=0

fail() {
    if [ "${PROGRESS_READY}" -eq 1 ]; then
        echo "0 0 0 FAILED: $1" >&3 2>/dev/null || true
    fi
    echo "[FAILED] $1"
    echo "MIGRATION FAILED: $1" > /dev/console 2>/dev/null || true

    if [ "${DESTRUCTIVE}" = "0" ]; then
        # Nothing has been formatted yet: restore the old OS's boot config and
        # reboot into it, instead of stranding a headless device in a debug
        # shell. The pre-migration script keeps .premigration backups.
        echo "No data touched yet — restoring previous OS boot config..."
        if [ "${PROGRESS_READY}" -eq 1 ]; then
            echo "0 0 0 FAILED: $1 - rebooting to old OS" >&3 2>/dev/null || true
        fi
        mkdir -p /mnt/bootfix
        if mount -t vfat "${BOOT_DEV}" /mnt/bootfix 2>/dev/null; then
            [ -f /mnt/bootfix/config.txt.premigration ] && \
                cp /mnt/bootfix/config.txt.premigration /mnt/bootfix/config.txt
            [ -f /mnt/bootfix/cmdline.txt.premigration ] && \
                cp /mnt/bootfix/cmdline.txt.premigration /mnt/bootfix/cmdline.txt
            rm -f /mnt/bootfix/nixos_migration
            sync
            umount /mnt/bootfix
            sleep 5
            reboot -f
        fi
        echo "Could not restore boot config — falling through to debug shell"
    fi

    echo "Dropping to shell for debugging..."
    exec /bin/sh
}

# set -e turns ANY uncaught failure into init exiting -> kernel panic
# ("Attempted to kill init"). Route it into fail() instead: fail() ends in
# exec or reboot, so the trap never re-fires.
trap 'fail "unexpected failure near stage ${STAGE_NUM}"' EXIT

if [ -f /migration_meta ]; then
    . /migration_meta
    export MIGRATION_DISPLAY_CLASS="${DISPLAY_CLASS:-}"
    export MIGRATION_DISPLAY_RESOLUTION="${DISPLAY_RESOLUTION:-}"
fi

show 28 "Starting upgrade"

# Wait for SD card device to appear
n=0
while [ ! -b "${BOOT_DEV}" ] && [ "${n}" -lt 30 ]; do
    sleep 1
    n=$((n + 1))
done
[ ! -b "${BOOT_DEV}" ] && fail "SD card not found after 30s: ${BOOT_DEV}"

show 30 "Upgrade started"

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

# Camera type: Pi OS selects the camera with a dtoverlay line in config.txt
# (switch_camera.py). The pre-migration copy is the unmodified one. NixOS
# reads the camera from /var/lib/pifinder/camera-type, written in Phase 8.
# The imx462 uses the imx290 driver. No overlay: NixOS uses its base camera.
CAMERA_TYPE=""
CAMERA_CONFIG=/mnt/bootchk/config.txt.premigration
[ -f "${CAMERA_CONFIG}" ] || CAMERA_CONFIG=/mnt/bootchk/config.txt
if [ -f "${CAMERA_CONFIG}" ]; then
    CAMERA_OVERLAY=$(sed -n 's/^[[:space:]]*dtoverlay=\(imx[0-9]*\).*/\1/p' \
        "${CAMERA_CONFIG}" | tail -n 1)
    case "${CAMERA_OVERLAY}" in
        imx296) CAMERA_TYPE=imx296 ;;
        imx290|imx462) CAMERA_TYPE=imx462 ;;
        imx477) CAMERA_TYPE=imx477 ;;
    esac
fi
umount /mnt/bootchk

# Read metadata written by pre-migration script
if [ ! -f /migration_meta ]; then
    fail "migration_meta not found in initramfs"
fi
. /migration_meta
# Now we have: TARBALL_PATH, TARBALL_SIZE, PIFINDER_DATA_PATH

# The tarball and the user data stay on the card, so only the tools and
# btrfs-convert need RAM.
MEM_KB=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
MEM_MB=$((MEM_KB / 1024))
echo "RAM available: ${MEM_MB} MB" > /dev/console 2>/dev/null || true

show 31 "Checks OK"

# -------------------------------------------------------------------
# Phase 2: Save WiFi credentials to RAM
# -------------------------------------------------------------------

show 33 "Saving WiFi"

mkdir -p "${MOUNT_ROOT}"
mount -t ext4 -o ro "${ROOT_DEV}" "${MOUNT_ROOT}" || fail "Cannot mount root"

mkdir -p /tmp/wifi/nm-connections

# Keyfiles generated by the pre-migration Python step (parses
# wpa_supplicant.conf on Debian, unit-tested). Bundled into the
# initramfs at /wifi-staged.
if [ -d /wifi-staged ]; then
    cp -a /wifi-staged/. /tmp/wifi/nm-connections/ 2>/dev/null || true
fi

# Any NM keyfiles the user already had on Debian — preserved as-is.
NM_SRC="${MOUNT_ROOT}/etc/NetworkManager/system-connections"
if [ -d "${NM_SRC}" ]; then
    cp -a "${NM_SRC}/." /tmp/wifi/nm-connections/ 2>/dev/null || true
fi

# -------------------------------------------------------------------
# Phase 3: Hostname
# -------------------------------------------------------------------

# Pi OS stores the hostname in /etc/hostname, the NixOS image reads it from
# PiFinder_data/hostname. Read it now; the old /etc is deleted in Phase 7.
# busybox tr has no character classes: '[:space:]' would delete the letters
# of the set, so name the whitespace characters.
OLD_HOSTNAME=""
if [ -s "${MOUNT_ROOT}/etc/hostname" ]; then
    OLD_HOSTNAME=$(head -n1 "${MOUNT_ROOT}/etc/hostname" | tr -d ' \t\r\n')
fi

# The access point name: Pi OS keeps it in hostapd.conf, NixOS in
# PiFinder_data/ap_name.
OLD_AP_NAME=""
if [ -f "${MOUNT_ROOT}/etc/hostapd/hostapd.conf" ]; then
    OLD_AP_NAME=$(sed -n 's/^ssid=//p' "${MOUNT_ROOT}/etc/hostapd/hostapd.conf" | head -n 1 | tr -d '\r\n')
fi

# Login credentials: the pifinder password hash, the SSH host keys and the
# user's authorized_keys. Kept in RAM now; written to the new root after the
# extraction. NixOS applies them once at the first boot (pifinder-migrated-
# credentials); the hash and host keys never go into PiFinder_data, which the
# network share exposes.
CARRY=/tmp/carry
mkdir -p "${CARRY}/ssh"
chmod 700 "${CARRY}"
if [ -f "${MOUNT_ROOT}/etc/shadow" ]; then
    awk -F: '$1 == "pifinder" {print $2}' "${MOUNT_ROOT}/etc/shadow" > "${CARRY}/password-hash"
fi
for key in "${MOUNT_ROOT}"/etc/ssh/ssh_host_*_key "${MOUNT_ROOT}"/etc/ssh/ssh_host_*_key.pub; do
    [ -f "${key}" ] || continue
    cp "${key}" "${CARRY}/ssh/" || echo "Cannot keep ${key}" > /dev/console
done
echo "SSH host keys kept: $(ls "${CARRY}/ssh" | wc -l)" > /dev/console 2>/dev/null || true
if [ -f "${MOUNT_ROOT}/home/pifinder/.ssh/authorized_keys" ]; then
    cp "${MOUNT_ROOT}/home/pifinder/.ssh/authorized_keys" "${CARRY}/authorized_keys"
fi

TARBALL_ON_ROOT="${MOUNT_ROOT}${TARBALL_PATH}"
[ -f "${TARBALL_ON_ROOT}" ] || { umount "${MOUNT_ROOT}"; fail "Tarball not found: ${TARBALL_PATH}"; }
umount "${MOUNT_ROOT}"

show 38 "Settings saved"

# -------------------------------------------------------------------
# Phase 4: Grow partition and ext4
# -------------------------------------------------------------------

# btrfs-convert writes its metadata into the free space of the ext4, and a
# full card has little. Grow the partition and the ext4 first. Both steps
# leave Pi OS bootable.
show 40 "Using full card"

echo ", +" | sfdisk -N 2 "${SD_DEV}" --no-reread 2>/dev/null || true
blockdev --rereadpt "${SD_DEV}" 2>/dev/null || true
sleep 1

show 42 "Checking card"
# e2fsck exit codes 0 and 1 mean clean or fixed; btrfs-convert needs a clean fs.
set +e
e2fsck -f -y "${ROOT_DEV}"
E2FSCK_RC=$?
set -e
[ "${E2FSCK_RC}" -le 1 ] || fail "e2fsck failed (${E2FSCK_RC})"

show 45 "Using full card"
# -f: the Pi has no RTC, so the initramfs clock is in 1970 and e2fsck stores a
# check time before the last mount. resize2fs would then ask for e2fsck again.
# The check above has just passed.
resize2fs -f "${ROOT_DEV}" || fail "resize2fs failed"

# -------------------------------------------------------------------
# Phase 5: Convert ext4 to btrfs
# -------------------------------------------------------------------

# btrfs-convert keeps every file, PiFinder_data with the catalog images
# included. It writes the btrfs superblock last, so a failure before the end
# leaves the ext4 intact and the old OS can still boot.
show 48 "Converting (long)"

for ko in /lib/modules/btrfs/*.ko; do
    [ -f "${ko}" ] && insmod "${ko}" 2>/dev/null || true
done
# The conversion takes many minutes, so the display shows the elapsed time
# every 5 s, and the percentage of inodes copied once btrfs-convert reports
# it ("copy inodes [o] [  1234/  5678]"). A display that does not move looks
# like a hang, and a user who thinks it hangs pulls the power.
btrfs-convert -l PIFINDER_SD "${ROOT_DEV}" > /tmp/convert.log 2>&1 &
CONVERT_PID=$!
CONVERT_START=$(date +%s)
while kill -0 "${CONVERT_PID}" 2>/dev/null; do
    ELAPSED=$(( $(date +%s) - CONVERT_START ))
    CLOCK=$(printf '%d:%02d' $((ELAPSED / 60)) $((ELAPSED % 60)))
    COUNTER=$(tr '\r' '\n' < /tmp/convert.log | grep -o '\[ *[0-9][0-9]*/ *[0-9][0-9]*\]' | tail -n 1 | sed 's/[^0-9\/]//g')
    if [ -n "${COUNTER}" ] && [ "${COUNTER#*/}" -gt 0 ]; then
        DONE_PCT=$(( ${COUNTER%/*} * 100 / ${COUNTER#*/} ))
        [ "${DONE_PCT}" -gt 99 ] && DONE_PCT=99
        show_update $((48 + DONE_PCT / 10)) "Converting ${DONE_PCT}% ${CLOCK}"
    else
        show_update 48 "Converting ${CLOCK}"
    fi
    sleep 5
done
set +e
wait "${CONVERT_PID}"
CONVERT_RC=$?
set -e
cat /tmp/convert.log
[ "${CONVERT_RC}" -eq 0 ] || fail "btrfs-convert failed (${CONVERT_RC})"

# Point of no return: the root is btrfs now.
DESTRUCTIVE=1
show 58 "Card converted"

mkdir -p "${MOUNT_NEW}"
mount -t btrfs -o compress=zstd:1,noatime "${ROOT_DEV}" "${MOUNT_NEW}" || fail "Cannot mount btrfs root"
btrfs filesystem resize max "${MOUNT_NEW}" || true
# btrfs-convert 5.10 (Debian 11) keeps the ext4 label and ignores -l.
btrfs filesystem label "${MOUNT_NEW}" PIFINDER_SD || true

# -------------------------------------------------------------------
# Phase 6: PiFinder_data subvolume
# -------------------------------------------------------------------

# PiFinder_data gets its own subvolume, so an upgrade can snapshot user data
# (ADR 0039). A reflink copy shares the data blocks, so it needs no space.
show 60 "Keeping your data"

HOME_NEW="${MOUNT_NEW}/home/pifinder"
DATA_OLD="${MOUNT_NEW}${PIFINDER_DATA_PATH}"
DATA_SUBVOL="${HOME_NEW}/PiFinder_data.subvol"
mkdir -p "${HOME_NEW}"
btrfs subvolume create "${DATA_SUBVOL}" || fail "Cannot create PiFinder_data subvolume"
if [ -d "${DATA_OLD}" ]; then
    # gcp is GNU cp from Pi OS: busybox cp has no --reflink.
    gcp -a --reflink=always "${DATA_OLD}/." "${DATA_SUBVOL}/" || fail "Cannot copy PiFinder_data"
    rm -rf "${DATA_OLD}"
fi
mv "${DATA_SUBVOL}" "${HOME_NEW}/PiFinder_data" || fail "Cannot rename PiFinder_data subvolume"

if [ -n "${OLD_HOSTNAME}" ] && [ ! -f "${HOME_NEW}/PiFinder_data/hostname" ]; then
    echo "${OLD_HOSTNAME}" > "${HOME_NEW}/PiFinder_data/hostname"
fi
if [ -n "${OLD_AP_NAME}" ] && [ ! -f "${HOME_NEW}/PiFinder_data/ap_name" ]; then
    echo "${OLD_AP_NAME}" > "${HOME_NEW}/PiFinder_data/ap_name"
fi

# -------------------------------------------------------------------
# Phase 7: Remove Pi OS
# -------------------------------------------------------------------

# Keep only PiFinder_data, the tarball, and ext2_saved (the ext4 image that
# btrfs-convert leaves for rollback; NixOS deletes it after the first good
# boot).
show 64 "Removing old system"

mv "${MOUNT_NEW}${TARBALL_PATH}" "${MOUNT_NEW}/.migration.tar.zst" || fail "Cannot move tarball"

for item in "${MOUNT_NEW}"/* "${MOUNT_NEW}"/.[!.]* "${MOUNT_NEW}"/..?*; do
    [ -e "${item}" ] || continue
    case "$(basename "${item}")" in
        ext2_saved|home|.migration.tar.zst) ;;
        *) rm -rf "${item}" || fail "Cannot remove ${item}" ;;
    esac
done
for item in "${MOUNT_NEW}"/home/* "${MOUNT_NEW}"/home/.[!.]*; do
    [ -e "${item}" ] || continue
    [ "$(basename "${item}")" = pifinder ] || rm -rf "${item}"
done
for item in "${HOME_NEW}"/* "${HOME_NEW}"/.[!.]* "${HOME_NEW}"/..?*; do
    [ -e "${item}" ] || continue
    [ "$(basename "${item}")" = PiFinder_data ] || rm -rf "${item}"
done

# -------------------------------------------------------------------
# Phase 8: Extract NixOS
# -------------------------------------------------------------------

show 68 "Installing NixOS"

zstd -d < "${MOUNT_NEW}/.migration.tar.zst" | tar xf - -C "${MOUNT_NEW}" || fail "Tarball extraction failed"
rm -f "${MOUNT_NEW}/.migration.tar.zst"

show 78 "Installing NixOS"

# The tarball's top-level boot/ is the FIRMWARE partition payload; rootfs/
# carries its own non-empty /boot (extlinux + kernels live on the btrfs root).
# Stage the firmware payload aside first or the rootfs move collides on "boot".
mv "${MOUNT_NEW}/boot" "${MOUNT_NEW}/.fw-staging" || fail "Cannot stage firmware payload"

cd "${MOUNT_NEW}/rootfs" || fail "rootfs missing from tarball"
for item in * .[!.]* ..?*; do
    [ -e "$item" ] || continue
    if [ "$item" = home ]; then
        # home/pifinder/PiFinder_data already exists as the subvolume; merge.
        mkdir -p "${MOUNT_NEW}/home"
        cp -a home/. "${MOUNT_NEW}/home/" || fail "Cannot merge rootfs/home"
        rm -rf home
        continue
    fi
    mv "$item" "${MOUNT_NEW}/" || fail "Cannot move rootfs/${item}"
done
cd /
rmdir "${MOUNT_NEW}/rootfs" || fail "rootfs dir not empty after move"

# NetworkManager refuses plugin files not owned by root, so normalise store
# ownership while the new root is still writable. (fix-nix-store-ownership on
# NixOS is the runtime backstop.)
chown -R 0:0 "${MOUNT_NEW}/nix/store" "${MOUNT_NEW}/nix/var/nix/db" 2>/dev/null || true
chown 0:0 "${MOUNT_NEW}" "${MOUNT_NEW}/home" 2>/dev/null || true

# -------------------------------------------------------------------
# Phase 9: Firmware partition
# -------------------------------------------------------------------

show 82 "Setting up boot"

mkfs.vfat -F 32 -n FIRMWARE "${BOOT_DEV}" || fail "mkfs.vfat failed"
mkdir -p "${MOUNT_BOOT}"
mount -t vfat "${BOOT_DEV}" "${MOUNT_BOOT}" || fail "Cannot mount boot"

cd "${MOUNT_NEW}/.fw-staging" || fail "firmware staging missing"
for item in *; do
    [ -e "$item" ] || continue
    cp -r "$item" "${MOUNT_BOOT}/$item" || fail "Cannot copy ${item} to firmware partition"
done
cd /
rm -rf "${MOUNT_NEW}/.fw-staging"
sync

# The firmware partition feeds the RPi firmware + U-Boot; extlinux.conf and
# the kernels live on the btrfs root (U-Boot reads them from mmc 0:2).
if [ ! -f "${MOUNT_BOOT}/config.txt" ]; then
    ls -lR "${MOUNT_BOOT}" >&2
    fail "config.txt missing from firmware partition after copy"
fi
if [ ! -f "${MOUNT_NEW}/boot/extlinux/extlinux.conf" ]; then
    ls -lR "${MOUNT_NEW}/boot" >&2
    fail "extlinux.conf missing from root /boot after move"
fi

# -------------------------------------------------------------------
# Phase 10: WiFi, owners, camera
# -------------------------------------------------------------------

show 88 "Restoring WiFi"

NM_DIR="${MOUNT_NEW}/etc/NetworkManager/system-connections"
mkdir -p "${NM_DIR}"
if [ -d /tmp/wifi/nm-connections ]; then
    cp -a /tmp/wifi/nm-connections/. "${NM_DIR}/" 2>/dev/null || true
    # NetworkManager refuses keyfiles not owned by root.
    chown -R 0:0 "${NM_DIR}" 2>/dev/null || true
    chmod 600 "${NM_DIR}"/*.nmconnection 2>/dev/null || true
fi

# pifinder user: UID 1000, GID 100 (users) on NixOS
chown -R 1000:100 "${HOME_NEW}" 2>/dev/null || true

# Login credentials from Phase 3.
MIGRATED="${MOUNT_NEW}/var/lib/pifinder/migrated"
mkdir -p "${MIGRATED}"
chmod 700 "${MIGRATED}"
[ -s "${CARRY}/password-hash" ] && cp "${CARRY}/password-hash" "${MIGRATED}/password-hash"
if ls "${CARRY}"/ssh/ssh_host_* >/dev/null 2>&1; then
    mkdir -p "${MIGRATED}/ssh"
    cp -p "${CARRY}"/ssh/ssh_host_* "${MIGRATED}/ssh/"
fi
chown -R 0:0 "${MIGRATED}"
if [ -s "${CARRY}/authorized_keys" ]; then
    mkdir -p "${HOME_NEW}/.ssh"
    cp "${CARRY}/authorized_keys" "${HOME_NEW}/.ssh/authorized_keys"
    chown -R 1000:100 "${HOME_NEW}/.ssh"
    chmod 700 "${HOME_NEW}/.ssh"
    chmod 600 "${HOME_NEW}/.ssh/authorized_keys"
fi

# Camera type from Phase 1; first boot selects the matching boot entry.
if [ -n "${CAMERA_TYPE}" ]; then
    mkdir -p "${MOUNT_NEW}/var/lib/pifinder"
    echo "${CAMERA_TYPE}" > "${MOUNT_NEW}/var/lib/pifinder/camera-type"
fi

show 92 "Saving to card"
sync
umount "${MOUNT_BOOT}" 2>/dev/null || true
umount "${MOUNT_NEW}" 2>/dev/null || true

# Final verification: the RPi firmware config must be on the FAT partition.
show 95 "Checking boot"
mkdir -p /mnt/bootchk
mount -t vfat -o ro "${BOOT_DEV}" /mnt/bootchk || fail "Cannot remount boot for verification"
if [ ! -f /mnt/bootchk/config.txt ]; then
    ls -lR /mnt/bootchk > /dev/console 2>&1 || true
    umount /mnt/bootchk 2>/dev/null || true
    fail "config.txt missing from firmware partition before reboot"
fi
umount /mnt/bootchk

show 100 "Done, restarting"
sleep 3

# Success: disarm the failure trap before the deliberate reboot.
trap - EXIT
echo "Rebooting into NixOS..." > /dev/console 2>/dev/null || true
reboot -f
