#!/usr/bin/env python3
"""PiFinder A/B Migration - Pre-flight Validation and Configuration

Validates the system for A/B partition migration and computes all
parameters needed by the initramfs migration script. Outputs a
shell-sourceable config file.

Must be run as root on the target Raspberry Pi.

Usage:
    sudo python3 migration_calc.py --output /tmp/migration_config.sh
    sudo python3 migration_calc.py --json
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple


# ── Partition Layout Constants ──────────────────────────────────────
#
# 4-partition MBR layout (all primary):
#   p1: boot     (FAT32, 256 MiB)   shared boot with os_prefix A/B
#   p2: root-a   (ext4, 3584 MiB)   active root
#   p3: root-b   (ext4, 3584 MiB)   update root
#   p4: data     (ext4, remaining)   user data (PiFinder_data)
#
# A/B switching uses os_prefix in autoboot.txt with tryboot.
# Boot partition contains a/ and b/ subdirectories, each with their
# own cmdline.txt pointing to p2 or p3 respectively.
#
# All sizes in MiB unless noted. Sector size is 512 bytes.
# 1 MiB = 2048 sectors.

BOOT_MIB = 256
ROOT_MIB = 3584  # 3.5 GiB
SECTORS_PER_MIB = 2048

# Partition table in sectors (512 bytes each)
# fmt: off
P1_START_S = 8192                    #    4 MiB  boot (RPi OS standard)
P1_SIZE_S  = BOOT_MIB * SECTORS_PER_MIB
P2_START_S = P1_START_S + P1_SIZE_S  #  260 MiB  root-a
P2_SIZE_S  = ROOT_MIB * SECTORS_PER_MIB
P3_START_S = P2_START_S + P2_SIZE_S  # 3844 MiB  root-b
P3_SIZE_S  = ROOT_MIB * SECTORS_PER_MIB
P4_START_S = P3_START_S + P3_SIZE_S  # 7428 MiB  data
# fmt: on

# The data partition (p4) starts here; everything before is fixed layout
FIXED_LAYOUT_END_MIB = P4_START_S // SECTORS_PER_MIB  # 7428 MiB

# Safety thresholds
MIN_SD_SIZE_GIB = 16
MIN_FREE_SPACE_MIB = 1024
MIN_BOOT_FREE_MIB = 10
MIN_RAM_MIB = 500
SHRINK_HEADROOM_MIB = 200  # Extra space kept when shrinking filesystem
BACKUP_END_BUFFER_MIB = 64  # Reserved at very end of SD card
USER_BACKUP_OVERHEAD = 1.05  # 5% overhead for tar headers (no compression)

# sfdisk partition table template (sector values filled in)
SFDISK_LAYOUT = f"""\
label: dos

/dev/mmcblk0p1 : start={P1_START_S}, size={P1_SIZE_S}, type=c, bootable
/dev/mmcblk0p2 : start={P2_START_S}, size={P2_SIZE_S}, type=83
/dev/mmcblk0p3 : start={P3_START_S}, size={P3_SIZE_S}, type=83
/dev/mmcblk0p4 : start={P4_START_S}, type=83
"""


@dataclass
class ValidationResult:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    checks: List[str] = field(default_factory=list)
    config: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def _run(cmd: list) -> Tuple[str, int]:
    """Run shell command, return (stdout, returncode)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout.strip(), result.returncode
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return str(e), 1


def _check_raspberry_pi(r: ValidationResult) -> bool:
    """Check 1: Verify running on Raspberry Pi."""
    model_path = Path("/proc/device-tree/model")
    if not model_path.exists():
        r.errors.append("Not running on Raspberry Pi")
        return False
    model = model_path.read_text().strip("\x00")
    r.checks.append(f"Detected: {model}")
    r.config["pi_model"] = model
    return True


def _check_sd_card(r: ValidationResult, device: str) -> bool:
    """Check 2: Verify SD card device exists."""
    if not os.path.exists(device):
        r.errors.append(f"{device} not found")
        return False
    r.checks.append(f"SD card device: {device}")
    return True


def _check_root_partition(r: ValidationResult, device: str) -> bool:
    """Check 3: Verify root is on the expected partition."""
    root_src, _ = _run(["findmnt", "-n", "-o", "SOURCE", "/"])
    expected = f"{device}p2"
    if root_src != expected:
        r.errors.append(
            f"Root not on {expected} (found: {root_src}). "
            "Migration only works on standard SD card layout."
        )
        return False
    r.checks.append(f"Root filesystem: {root_src}")
    return True


def _check_sd_size(r: ValidationResult, device: str) -> bool:
    """Check 4: Verify SD card is large enough."""
    size_str, rc = _run(["blockdev", "--getsize64", device])
    if rc != 0:
        r.errors.append("Cannot read SD card size")
        return False

    sd_bytes = int(size_str)
    sd_mib = sd_bytes // (1024 * 1024)
    sd_gib = sd_bytes / (1024**3)

    if sd_gib < MIN_SD_SIZE_GIB:
        r.errors.append(
            f"SD card too small: {sd_gib:.1f} GiB (need {MIN_SD_SIZE_GIB} GiB+)"
        )
        return False

    r.checks.append(f"SD card size: {sd_gib:.1f} GiB ({sd_mib} MiB)")
    r.config["sd_size_bytes"] = sd_bytes
    r.config["sd_size_mib"] = sd_mib
    return True


def _check_free_space(r: ValidationResult) -> bool:
    """Check 5: Verify enough free space on root.

    Excludes /home/pifinder/PiFinder_data from usage calculation since
    it will be moved to the separate data partition during migration.
    """
    st = os.statvfs("/")
    free_mib = (st.f_bavail * st.f_frsize) // (1024 * 1024)
    total_used_mib = ((st.f_blocks - st.f_bfree) * st.f_frsize) // (1024 * 1024)

    # Subtract PiFinder_data since it moves to data partition
    pifinder_data = Path("/home/pifinder/PiFinder_data")
    data_mib = 0
    if pifinder_data.exists():
        out, rc = _run(["du", "-sm", str(pifinder_data)])
        if rc == 0:
            try:
                data_mib = int(out.split()[0])
            except (ValueError, IndexError):
                pass

    used_mib = total_used_mib - data_mib

    if free_mib < MIN_FREE_SPACE_MIB:
        r.errors.append(
            f"Insufficient free space: {free_mib} MiB (need {MIN_FREE_SPACE_MIB} MiB)"
        )
        return False

    r.checks.append(
        f"Root usage: {used_mib} MiB (excluding {data_mib} MiB PiFinder_data)"
    )
    r.config["root_used_mib"] = used_mib
    r.config["root_free_mib"] = free_mib
    r.config["pifinder_data_mib"] = data_mib
    return True


def _check_root_fits(r: ValidationResult) -> bool:
    """Check 6: Verify current root usage fits in new partition."""
    used_mib = r.config.get("root_used_mib", 0)
    max_allowed = ROOT_MIB - SHRINK_HEADROOM_MIB

    if used_mib > max_allowed:
        r.errors.append(
            f"Root uses {used_mib} MiB but new root partition is {ROOT_MIB} MiB "
            f"(max usable: {max_allowed} MiB with {SHRINK_HEADROOM_MIB} MiB headroom)"
        )
        return False

    r.checks.append(f"Root usage ({used_mib} MiB) fits in {ROOT_MIB} MiB partition")
    return True


def _check_sd_health(r: ValidationResult, device: str) -> bool:
    """Check 7: Verify SD card is not failing."""
    try:
        with open("/proc/mounts") as f:
            for line in f:
                if f"{device}p2" in line and ",ro," in line:
                    r.errors.append("SD card is mounted read-only (possibly failing)")
                    return False
    except OSError:
        pass

    dmesg_out, _ = _run(["dmesg"])
    io_errors = [
        line.strip()
        for line in dmesg_out.split("\n")
        if "mmcblk0" in line.lower()
        and ("error" in line.lower() or "fail" in line.lower())
    ]
    if io_errors:
        r.warnings.append("SD card showing I/O errors in dmesg:")
        for line in io_errors[-3:]:
            r.warnings.append(f"  {line}")
    else:
        r.checks.append("SD card health: OK")
    return True


def _check_required_tools(r: ValidationResult) -> bool:
    """Check 8: Verify all required tools are installed."""
    required = [
        "sfdisk",
        "dd",
        "mkfs.ext4",
        "e2fsck",
        "resize2fs",
        "dumpe2fs",
        "cpio",
        "gzip",
        "zstd",
        "blkid",
        "md5sum",
        "partprobe",
    ]
    missing = [t for t in required if not shutil.which(t)]
    if missing:
        r.errors.append(f"Missing required tools: {', '.join(missing)}")
        return False
    r.checks.append("Required tools: all present")
    return True


def _check_boot_partition(r: ValidationResult) -> bool:
    """Check 9: Verify boot partition is accessible with enough space."""
    # Detect boot mount point (Bullseye: /boot, Bookworm: /boot/firmware)
    for boot_dir in ("/boot/firmware", "/boot"):
        boot_src, rc = _run(["findmnt", "-n", "-o", "SOURCE", boot_dir])
        if rc == 0 and boot_src:
            break
    else:
        r.errors.append("Boot partition is not mounted at /boot or /boot/firmware")
        return False

    try:
        st = os.statvfs(boot_dir)
        free_mib = (st.f_bavail * st.f_frsize) // (1024 * 1024)
    except OSError:
        r.errors.append(f"Cannot stat {boot_dir}")
        return False

    if free_mib < MIN_BOOT_FREE_MIB:
        r.errors.append(
            f"Insufficient space in {boot_dir}: {free_mib} MiB "
            f"(need {MIN_BOOT_FREE_MIB} MiB)"
        )
        return False

    r.checks.append(f"Boot partition: {boot_src} at {boot_dir} ({free_mib} MiB free)")
    r.config["boot_dir"] = boot_dir
    return True


def _check_system_state(r: ValidationResult) -> bool:
    """Check 10: Verify system is not degraded."""
    state, _ = _run(["systemctl", "is-system-running"])
    if state in ("degraded", "maintenance"):
        r.warnings.append(
            f"System is in '{state}' state; some services may have failed"
        )
    else:
        r.checks.append(f"System state: {state}")
    return True


def _compute_backup_params(r: ValidationResult, essential_only: bool = False) -> bool:
    """Compute backup offsets and validate they fit on the SD card.

    Backup layout at END of SD card (working backwards from end):
        [...partitions...] [root_backup] [user_data_tar] [64 MiB buffer]

    No boot backup needed — boot partition (p1) is unchanged by migration.
    User data is moved (tar to raw SD, delete from root) so only one
    copy exists at a time.
    """
    sd_mib = r.config["sd_size_mib"]
    used_mib = r.config["root_used_mib"]

    # The init script will use resize2fs -M to shrink to minimum, then
    # read the actual size via dumpe2fs. For pre-flight validation, we
    # estimate the shrunk size as used_space + headroom.
    shrink_estimate_mib = used_mib + SHRINK_HEADROOM_MIB
    r.config["shrink_estimate_mib"] = shrink_estimate_mib

    # Measure user data
    pifinder_data = Path("/home/pifinder/PiFinder_data")
    total_data_mib = 0

    if pifinder_data.exists():
        if essential_only:
            # Only measure essential files (databases, configs, obslists)
            # Excludes: captures/, logs/, solver_debug_dumps/, screenshots/
            out, rc = _run(
                [
                    "du",
                    "-sm",
                    "--exclude=captures",
                    "--exclude=logs",
                    "--exclude=solver_debug_dumps",
                    "--exclude=screenshots",
                    "--exclude=images",
                    "--exclude=*.fits",
                    "--exclude=*.png",
                    "--exclude=*.jpg",
                    "--exclude=*.jpeg",
                    "--exclude=*.bmp",
                    str(pifinder_data),
                ]
            )
        else:
            out, rc = _run(["du", "-sm", str(pifinder_data)])
        if rc == 0:
            try:
                total_data_mib = int(out.split()[0])
            except (ValueError, IndexError):
                pass

    r.config["user_total_data_mib"] = total_data_mib
    r.config["pifinder_data_mib"] = total_data_mib
    r.config["essential_only"] = 1 if essential_only else 0

    # User backup size (ALL user data with tar overhead).
    user_backup_mib = int(total_data_mib * USER_BACKUP_OVERHEAD) + 10
    r.config["user_backup_size_mib"] = user_backup_mib

    # Backup layout at END of SD card (working backwards):
    #   [...partitions...] [root_backup] [user_data_tar] [buffer]
    backup_end_mib = sd_mib - BACKUP_END_BUFFER_MIB

    # User data tar goes at the very end (before buffer)
    user_backup_start = backup_end_mib - user_backup_mib

    # Root backup goes before user data tar (no boot backup needed)
    root_backup_start = user_backup_start - shrink_estimate_mib

    r.config["root_backup_offset_mib"] = root_backup_start

    # Verify backup region doesn't overlap with new partition layout
    if root_backup_start < FIXED_LAYOUT_END_MIB:
        r.errors.append(
            f"SD card too small for safe backup: "
            f"leftmost backup at {root_backup_start} MiB but "
            f"new partitions extend to {FIXED_LAYOUT_END_MIB} MiB"
        )
        return False

    safety_gap = root_backup_start - FIXED_LAYOUT_END_MIB
    r.checks.append(
        f"Backup layout (end of SD): root@{root_backup_start}, "
        f"user@{user_backup_start} MiB "
        f"(safety gap: {safety_gap} MiB)"
    )

    if total_data_mib > 0:
        r.checks.append(
            f"User data: {total_data_mib} MiB (move to SD, backup: {user_backup_mib} MiB)"
        )
    else:
        r.checks.append("User data: none or empty")

    # Data partition size after migration
    data_mib = sd_mib - FIXED_LAYOUT_END_MIB
    r.config["data_partition_mib"] = data_mib
    r.checks.append(f"Data partition after migration: ~{data_mib} MiB")

    return True


def validate(
    device: str = "/dev/mmcblk0", essential_only: bool = False
) -> ValidationResult:
    """Run all pre-flight checks and compute migration parameters."""
    r = ValidationResult()

    # Store layout constants in config for the init script
    r.config["boot_mib"] = BOOT_MIB
    r.config["root_mib"] = ROOT_MIB
    r.config["fixed_layout_end_mib"] = FIXED_LAYOUT_END_MIB
    r.config["backup_end_buffer_mib"] = BACKUP_END_BUFFER_MIB
    r.config["device"] = device

    # Sequential checks (later checks depend on earlier ones)
    checks = [
        lambda: _check_raspberry_pi(r),
        lambda: _check_sd_card(r, device),
        lambda: _check_root_partition(r, device),
        lambda: _check_sd_size(r, device),
        lambda: _check_free_space(r),
        lambda: _check_root_fits(r),
        lambda: _check_sd_health(r, device),
        lambda: _check_required_tools(r),
        lambda: _check_boot_partition(r),
        lambda: _check_system_state(r),
        lambda: _compute_backup_params(r, essential_only),
    ]

    for check in checks:
        if not check() and r.errors:
            break  # Stop on first error

    return r


def write_shell_config(config: dict, path: str) -> None:
    """Write config as shell-sourceable file."""
    with open(path, "w") as f:
        f.write("# PiFinder A/B Migration Configuration\n")
        f.write("# Auto-generated by migration_calc.py — DO NOT EDIT\n\n")
        for key in sorted(config):
            val = config[key]
            if isinstance(val, str):
                f.write(f'{key.upper()}="{val}"\n')
            else:
                f.write(f"{key.upper()}={val}\n")

    # Also write the sfdisk layout
    sfdisk_path = path.replace("_config.sh", "_sfdisk.txt")
    with open(sfdisk_path, "w") as f:
        f.write(SFDISK_LAYOUT)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PiFinder A/B Migration — Pre-flight Validation"
    )
    parser.add_argument("--device", default="/dev/mmcblk0", help="SD card device path")
    parser.add_argument(
        "--output",
        default="/tmp/migration_config.sh",
        help="Path for shell config output",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print JSON to stdout instead of shell vars"
    )
    parser.add_argument(
        "--essential-only",
        action="store_true",
        help="Only back up essential user data (databases, configs, obslists)",
    )
    args = parser.parse_args()

    result = validate(args.device, essential_only=args.essential_only)

    # Print results
    for msg in result.checks:
        print(f"  OK    {msg}")
    for msg in result.warnings:
        print(f"  WARN  {msg}")
    for msg in result.errors:
        print(f"  FAIL  {msg}", file=sys.stderr)

    if not result.ok:
        n = len(result.errors)
        print(f"\nValidation failed with {n} error(s).", file=sys.stderr)
        sys.exit(1)

    print(f"\nAll {len(result.checks)} checks passed.")

    if args.json:
        json.dump(result.config, sys.stdout, indent=2)
        print()
    else:
        write_shell_config(result.config, args.output)
        print(f"Config written to: {args.output}")

    sys.exit(0)


if __name__ == "__main__":
    main()
