#!/usr/bin/env bash
set -euo pipefail

# Deploy PiFinder NixOS netboot configuration to proxnix
#
# Builds the pifinder-netboot closure (NFS root baked in), copies the nix store
# closure to NFS, and sets up TFTP with kernel/initrd/firmware for PXE boot.
#
# Boot sequence: Pi firmware → u-boot → extlinux/extlinux.conf (TFTP) → NFS root

PROXNIX="mike@192.168.5.12"
NFS_ROOT="/srv/nfs/pifinder"
TFTP_ROOT="/srv/tftp"
PI_IP="192.168.5.150"
PI_MAC="e4-5f-01-b7-37-31"  # For PXE boot speedup

# SSH options to prevent timeout during long transfers
SSH_OPTS="-o ServerAliveInterval=30 -o ServerAliveCountMax=10"
export RSYNC_RSH="ssh ${SSH_OPTS}"

SSH_PUBKEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGrPg9hSgxwg0EECxXSpYi7t3F/w/BgpymlD1uUDedRz mike@nixtop"

# Password hash for "solveit"
SHADOW_HASH='$6$upbQ1/Jfh7zDiIYW$jPVQdYJCZn/Pe/OIGx89DZm9trIhEJp7Q4LNZsq/5x9csj6U08.P2avebrQIDJCEyD0xipsV6C19Sr5iAbCuv1'

# ── Helpers ──────────────────────────────────────────────────────────────────

run_proxnix() {
    ssh ${SSH_OPTS} "${PROXNIX}" "bash -euo pipefail -c \"$1\""
}

# ── Build netboot closure ────────────────────────────────────────────────────

echo "=== Building pifinder-netboot closure ==="
nix build .#nixosConfigurations.pifinder-netboot.config.system.build.toplevel \
    -o result-netboot --system aarch64-linux

CLOSURE=$(readlink -f result-netboot)
echo "Closure: $CLOSURE"

# Extract camera type from NixOS config for config.txt dtoverlay
CAMERA_TYPE=$(nix eval .#nixosConfigurations.pifinder-netboot.config.pifinder.cameraType --raw)
echo "Camera: $CAMERA_TYPE"

# Extract paths from closure
KERNEL=$(readlink -f result-netboot/kernel)
INITRD=$(readlink -f result-netboot/initrd)
DTBS=$(readlink -f result-netboot/dtbs)
INIT_PATH="${CLOSURE}/init"

KERNEL_NAME=$(basename "$(dirname "$KERNEL")")-Image
INITRD_NAME=$(basename "$(dirname "$INITRD")")-initrd

echo "Kernel: $KERNEL"
echo "Initrd: $INITRD"
echo "DTBs:   $DTBS"
echo "Init:   $INIT_PATH"

# ── Stop TFTP — prevent Pi from netbooting during deploy ─────────────────────

echo "Stopping TFTP server..."
ssh "${PROXNIX}" "sudo systemctl stop atftpd.service"

# ── Halt Pi if running — prevent NFS corruption ──────────────────────────────

if ssh -o ConnectTimeout=3 -o BatchMode=yes "pifinder@${PI_IP}" "echo ok" 2>/dev/null; then
    echo "Pi is running — halting..."
    ssh "pifinder@${PI_IP}" "echo solveit | sudo -S poweroff" 2>/dev/null || true
    echo "Waiting for Pi to go down..."
    sleep 3
    while ping -c1 -W1 "${PI_IP}" &>/dev/null; do sleep 1; done
    echo "Pi is down"
else
    echo "Pi not reachable, proceeding"
fi

# ── Backup SSH host keys ─────────────────────────────────────────────────────

echo "Backing up SSH host keys..."
ssh "${PROXNIX}" "sudo cp -a ${NFS_ROOT}/etc/ssh/ssh_host_* /tmp/ 2>/dev/null || true"

# ── Copy nix store closure to NFS ────────────────────────────────────────────

echo "Copying nix store closure to NFS..."
ssh "${PROXNIX}" "sudo mkdir -p ${NFS_ROOT}/nix/store"

# Get list of store paths and stream via tar (fast, handles duplicates via overwrite)
STORE_PATHS=$(nix path-info -r "$CLOSURE")
TOTAL_PATHS=$(echo "$STORE_PATHS" | wc -l)
echo "Streaming ${TOTAL_PATHS} store paths via tar..."

# Rsync store paths with -R to preserve directory structure
# shellcheck disable=SC2086
rsync -avR --rsync-path="sudo rsync" $STORE_PATHS "${PROXNIX}:${NFS_ROOT}/"
echo "Transfer complete"

# ── Set up NFS root directory structure ──────────────────────────────────────

echo "Setting up NFS root directory structure..."
ssh "${PROXNIX}" "sudo bash -euo pipefail" << SETUP
# Create standard directories (bin/usr are symlinks, not dirs)
mkdir -p ${NFS_ROOT}/{etc/ssh,home/pifinder/.ssh,root/.ssh,var,tmp,proc,sys,dev,run,boot}
chmod 1777 ${NFS_ROOT}/tmp

# Symlinks from NixOS system (remove existing dirs/symlinks first)
rm -rf ${NFS_ROOT}/bin ${NFS_ROOT}/usr
ln -sfT ${CLOSURE}/sw/bin ${NFS_ROOT}/bin
ln -sfT ${CLOSURE}/sw ${NFS_ROOT}/usr

# /etc/static points to the NixOS etc derivation (required for PAM, etc.)
ln -sfT ${CLOSURE}/etc ${NFS_ROOT}/etc/static

# Critical /etc symlinks that NixOS activation would normally create
ln -sfT /etc/static/pam.d ${NFS_ROOT}/etc/pam.d
ln -sfT /etc/static/bashrc ${NFS_ROOT}/etc/bashrc
# passwd/shadow/group are created as real files later (need to be writable for netboot)
rm -f ${NFS_ROOT}/etc/passwd ${NFS_ROOT}/etc/shadow ${NFS_ROOT}/etc/group 2>/dev/null || true
ln -sfT /etc/static/sudoers ${NFS_ROOT}/etc/sudoers 2>/dev/null || true
ln -sfT /etc/static/sudoers.d ${NFS_ROOT}/etc/sudoers.d 2>/dev/null || true
ln -sfT /etc/static/nsswitch.conf ${NFS_ROOT}/etc/nsswitch.conf 2>/dev/null || true
ln -sfT /etc/static/systemd ${NFS_ROOT}/etc/systemd 2>/dev/null || true
ln -sfT /etc/static/polkit-1 ${NFS_ROOT}/etc/polkit-1 2>/dev/null || true

# Create nix profile symlinks
mkdir -p ${NFS_ROOT}/nix/var/nix/profiles
ln -sfT ${CLOSURE} ${NFS_ROOT}/nix/var/nix/profiles/system
ln -sfT ${CLOSURE} ${NFS_ROOT}/run/current-system 2>/dev/null || true
SETUP

# ── Restore SSH host keys ────────────────────────────────────────────────────

echo "Restoring/generating SSH host keys..."
ssh "${PROXNIX}" "bash -euo pipefail -c '
if ls /tmp/ssh_host_* >/dev/null 2>&1; then
    sudo cp -a /tmp/ssh_host_* ${NFS_ROOT}/etc/ssh/
    echo \"Restored existing host keys\"
else
    sudo ssh-keygen -A -f ${NFS_ROOT}
    echo \"Generated new host keys\"
fi
'"

# ── Link NixOS /etc files ────────────────────────────────────────────────────

echo "Linking NixOS etc files..."
ssh "${PROXNIX}" "sudo bash -euo pipefail -c '
ln -sf ${CLOSURE}/etc/ssh/sshd_config ${NFS_ROOT}/etc/ssh/sshd_config
ln -sf ${CLOSURE}/etc/ssh/ssh_config ${NFS_ROOT}/etc/ssh/ssh_config 2>/dev/null || true
ln -sf ${CLOSURE}/etc/ssh/moduli ${NFS_ROOT}/etc/ssh/moduli 2>/dev/null || true
ln -sfT ${CLOSURE}/etc/pam.d ${NFS_ROOT}/etc/pam.d
ln -sf ${CLOSURE}/etc/nsswitch.conf ${NFS_ROOT}/etc/nsswitch.conf 2>/dev/null || true
'"

# ── Static user files ────────────────────────────────────────────────────────

echo "Creating static user files..."

ssh "${PROXNIX}" "sudo tee ${NFS_ROOT}/etc/passwd > /dev/null" << 'PASSWD'
root:x:0:0:System administrator:/root:/run/current-system/sw/bin/bash
pifinder:x:1000:100::/home/pifinder:/run/current-system/sw/bin/bash
nobody:x:65534:65534:Unprivileged account:/var/empty:/run/current-system/sw/bin/nologin
sshd:x:993:993:SSH daemon user:/var/empty:/run/current-system/sw/bin/nologin
avahi:x:994:994:Avahi daemon user:/var/empty:/run/current-system/sw/bin/nologin
gpsd:x:992:992:GPSD daemon user:/var/empty:/run/current-system/sw/bin/nologin
PASSWD

ssh "${PROXNIX}" "sudo tee ${NFS_ROOT}/etc/group > /dev/null" << 'GROUP'
root:x:0:
wheel:x:1:pifinder
users:x:100:pifinder
kmem:x:9:pifinder
input:x:174:pifinder
nobody:x:65534:
spi:x:996:pifinder
i2c:x:997:pifinder
gpio:x:998:pifinder
dialout:x:995:pifinder
video:x:994:pifinder
networkmanager:x:993:pifinder
sshd:x:993:
avahi:x:994:
gpsd:x:992:
GROUP

ssh "${PROXNIX}" "echo 'root:${SHADOW_HASH}:1::::::
pifinder:${SHADOW_HASH}:1::::::
nobody:!:1::::::
sshd:!:1::::::
avahi:!:1::::::
gpsd:!:1::::::' | sudo tee ${NFS_ROOT}/etc/shadow > /dev/null"

run_proxnix "sudo chmod 644 ${NFS_ROOT}/etc/passwd ${NFS_ROOT}/etc/group"
run_proxnix "sudo chmod 640 ${NFS_ROOT}/etc/shadow"

# ── SSH authorized_keys ──────────────────────────────────────────────────────

echo "Setting up SSH authorized_keys..."
ssh "${PROXNIX}" "echo '${SSH_PUBKEY}' | sudo tee ${NFS_ROOT}/home/pifinder/.ssh/authorized_keys > /dev/null"
ssh "${PROXNIX}" "echo '${SSH_PUBKEY}' | sudo tee ${NFS_ROOT}/root/.ssh/authorized_keys > /dev/null"
run_proxnix "sudo chown -R 1000:100 ${NFS_ROOT}/home/pifinder"
run_proxnix "sudo chmod 700 ${NFS_ROOT}/home/pifinder/.ssh ${NFS_ROOT}/root/.ssh"
run_proxnix "sudo chmod 600 ${NFS_ROOT}/home/pifinder/.ssh/authorized_keys ${NFS_ROOT}/root/.ssh/authorized_keys"

# ── PiFinder symlink ─────────────────────────────────────────────────────────

echo "Setting up PiFinder directory..."
# Find pifinder-src from the current closure (not just any old one in the store)
PFSRC_REL=$(nix path-info -r "$CLOSURE" | grep pifinder-src | head -1)
echo "PiFinder source from closure: $PFSRC_REL"
ssh "${PROXNIX}" "sudo bash -euo pipefail -c '
PFSRC=\"${NFS_ROOT}${PFSRC_REL}\"
if [ ! -d \"\$PFSRC\" ]; then
    echo \"ERROR: pifinder-src not found: \$PFSRC\"
    exit 1
fi
PFHOME=${NFS_ROOT}/home/pifinder/PiFinder

echo \"PiFinder source: ${PFSRC_REL}\"

[ -L \"\$PFHOME\" ] && rm \"\$PFHOME\"
[ -d \"\$PFHOME\" ] && rm -rf \"\$PFHOME\"

ln -sfT \"${PFSRC_REL}\" \"\$PFHOME\"

mkdir -p ${NFS_ROOT}/home/pifinder/PiFinder_data
chown 1000:100 ${NFS_ROOT}/home/pifinder/PiFinder_data
'"

# ── Copy firmware to TFTP (from raspberrypi firmware package) ────────────────

echo "Copying firmware to TFTP..."
FW_PKG=$(nix build nixpkgs#raspberrypifw --print-out-paths --system aarch64-linux 2>/dev/null)
ssh "${PROXNIX}" "sudo mkdir -p ${TFTP_ROOT}"

# Copy firmware files
rsync -avz "${FW_PKG}/share/raspberrypi/boot/"*.{elf,dat,bin,dtb} "${PROXNIX}:/tmp/fw/"
ssh "${PROXNIX}" "sudo cp /tmp/fw/* ${TFTP_ROOT}/ && rm -rf /tmp/fw"

# Copy custom u-boot with network boot priority
UBOOT=$(nix build .#packages.aarch64-linux.uboot-netboot --print-out-paths --system aarch64-linux 2>/dev/null)
echo "Using custom u-boot: $UBOOT"
rsync -avz "${UBOOT}/u-boot.bin" "${PROXNIX}:/tmp/u-boot-rpi4.bin"
ssh "${PROXNIX}" "sudo mv /tmp/u-boot-rpi4.bin ${TFTP_ROOT}/"

# ── Copy kernel, initrd, DTBs to TFTP ────────────────────────────────────────

echo "Copying kernel/initrd/DTBs to TFTP..."
ssh "${PROXNIX}" "sudo mkdir -p ${TFTP_ROOT}/nixos"
rsync -avz "${KERNEL}" "${PROXNIX}:/tmp/${KERNEL_NAME}"
rsync -avz "${INITRD}" "${PROXNIX}:/tmp/${INITRD_NAME}"
ssh "${PROXNIX}" "sudo mv /tmp/${KERNEL_NAME} /tmp/${INITRD_NAME} ${TFTP_ROOT}/nixos/"

# Copy DTBs from device-tree-overlays package
rsync -avz "${DTBS}/broadcom/" "${PROXNIX}:/tmp/dtbs/"
ssh "${PROXNIX}" "sudo cp /tmp/dtbs/*.dtb ${TFTP_ROOT}/ && sudo rm -rf /tmp/dtbs"

# Copy overlays from kernel package
KERNEL_DIR=$(dirname "$KERNEL")
rsync -avz "${KERNEL_DIR}/dtbs/overlays/" "${PROXNIX}:/tmp/overlays/"
ssh "${PROXNIX}" "sudo rm -rf ${TFTP_ROOT}/overlays && sudo mv /tmp/overlays ${TFTP_ROOT}/"

# ── Write config.txt for u-boot ──────────────────────────────────────────────

echo "Writing config.txt..."
ssh "${PROXNIX}" "sudo tee ${TFTP_ROOT}/config.txt > /dev/null" << CONFIG
[pi4]
kernel=u-boot-rpi4.bin
enable_gic=1
armstub=armstub8-gic.bin

disable_overscan=1
arm_boost=1

# Camera overlay from NixOS config
dtoverlay=${CAMERA_TYPE}

[all]
arm_64bit=1
enable_uart=1
avoid_warnings=1
CONFIG

# ── Generate extlinux/extlinux.conf ────────────────────────────────────────────

echo "Generating extlinux/extlinux.conf..."
ssh "${PROXNIX}" "sudo mkdir -p ${TFTP_ROOT}/extlinux && sudo tee ${TFTP_ROOT}/extlinux/extlinux.conf > /dev/null" << EXTLINUX
TIMEOUT 10
DEFAULT nixos-default

LABEL nixos-default
  MENU LABEL NixOS - Default
  LINUX /nixos/${KERNEL_NAME}
  INITRD /nixos/${INITRD_NAME}
  APPEND init=${INIT_PATH} ip=dhcp console=ttyS0,115200n8 console=ttyAMA0,115200n8 console=tty0 loglevel=4
EXTLINUX

# ── Create pxelinux.cfg for faster MAC-based boot ─────────────────────────────

echo "Creating pxelinux.cfg/01-${PI_MAC}..."
ssh "${PROXNIX}" "sudo mkdir -p ${TFTP_ROOT}/pxelinux.cfg && sudo ln -sf ../extlinux/extlinux.conf ${TFTP_ROOT}/pxelinux.cfg/01-${PI_MAC}"

# ── Clean up old artifacts ───────────────────────────────────────────────────

echo "Cleaning up old artifacts..."
ssh "${PROXNIX}" "sudo rm -f ${TFTP_ROOT}/cmdline.txt ${TFTP_ROOT}/nixos/patched-initrd 2>/dev/null || true"
ssh "${PROXNIX}" "sudo rm -f /tmp/ssh_host_*"

# ── Restart TFTP ─────────────────────────────────────────────────────────────

echo "Restarting TFTP server..."
ssh "${PROXNIX}" "sudo systemctl start atftpd.service"

# ── Verification ─────────────────────────────────────────────────────────────

echo ""
echo "=========================================="
echo "VERIFYING DEPLOYMENT CONSISTENCY"
echo "=========================================="
VERIFY_FAILED=0

echo -n "Checking u-boot... "
if ssh "${PROXNIX}" "test -f ${TFTP_ROOT}/u-boot-rpi4.bin"; then
    echo "OK"
else
    echo "FAILED"
    VERIFY_FAILED=1
fi

echo -n "Checking config.txt... "
if ssh "${PROXNIX}" "grep -q 'kernel=u-boot-rpi4.bin' ${TFTP_ROOT}/config.txt"; then
    echo "OK"
else
    echo "FAILED"
    VERIFY_FAILED=1
fi

echo -n "Checking extlinux/extlinux.conf... "
if ssh "${PROXNIX}" "test -f ${TFTP_ROOT}/extlinux/extlinux.conf"; then
    echo "OK"
else
    echo "FAILED"
    VERIFY_FAILED=1
fi

echo -n "Checking kernel... "
if ssh "${PROXNIX}" "test -f ${TFTP_ROOT}/nixos/${KERNEL_NAME}"; then
    echo "OK"
else
    echo "FAILED"
    VERIFY_FAILED=1
fi

echo -n "Checking initrd... "
if ssh "${PROXNIX}" "test -f ${TFTP_ROOT}/nixos/${INITRD_NAME}"; then
    echo "OK"
else
    echo "FAILED"
    VERIFY_FAILED=1
fi

echo -n "Checking NFS closure... "
if ssh "${PROXNIX}" "test -f ${NFS_ROOT}${INIT_PATH}"; then
    echo "OK"
else
    echo "FAILED"
    VERIFY_FAILED=1
fi

echo -n "Checking PiFinder symlink... "
PFSRC_TARGET=$(ssh "${PROXNIX}" "readlink ${NFS_ROOT}/home/pifinder/PiFinder 2>/dev/null || true")
if [ -n "$PFSRC_TARGET" ] && ssh "${PROXNIX}" "test -d ${NFS_ROOT}${PFSRC_TARGET}/python"; then
    echo "OK"
else
    echo "FAILED"
    VERIFY_FAILED=1
fi

echo "=========================================="

if [ $VERIFY_FAILED -eq 1 ]; then
    echo "=== DEPLOY FAILED VERIFICATION — DO NOT BOOT ==="
    exit 1
fi

echo "=== Deploy complete and verified ==="
echo ""
echo "Boot chain: Pi firmware → u-boot → extlinux/extlinux.conf → NFS root"
echo "To boot the Pi: power cycle it"
