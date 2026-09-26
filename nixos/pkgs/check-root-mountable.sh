#!/usr/bin/env bash
# Exit 0 if the NixOS system at $1 can mount the root file system that is
# mounted now, else print the reason and exit 1.
#
# The root line in the system's etc/fstab must name a device that resolves to
# the mounted root device, and a type that is "auto" or the mounted type. A
# build that fails this stops in the initrd, before the boot watchdog can
# roll it back (ADR 0039). Same rule as check_root_mountable in
# python/PiFinder/nixos_upgrade.py.
#
# MOUNTS_FILE overrides /proc/mounts, for tests.
set -euo pipefail

system=$1
mounts=${MOUNTS_FILE:-/proc/mounts}

read -r device fs_type < <(awk '$1 !~ /^#/ && $2 == "/" { print $1, $3; exit }' "$system/etc/fstab" 2>/dev/null) || true
if [ -z "${device:-}" ]; then
  echo "$system has no root file system in etc/fstab"
  exit 1
fi

# The last entry for / is the one on top.
read -r root_device root_type < <(awk '$2 == "/" { d = $1; t = $3 } END { print d, t }' "$mounts")

if [ ! -e "$device" ] || [ "$(readlink -f "$device")" != "$(readlink -f "$root_device")" ]; then
  echo "$system mounts / from $device, but the root file system is $root_device"
  exit 1
fi
if [ "$fs_type" != auto ] && [ "$fs_type" != "$root_type" ]; then
  echo "$system mounts / as $fs_type, but the root file system is $root_type"
  exit 1
fi
