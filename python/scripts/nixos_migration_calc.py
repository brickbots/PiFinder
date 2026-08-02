#!/usr/bin/env python3
"""
Pre-flight checks for NixOS migration.

Validates hardware requirements before migration can proceed.
Run on the Pi to verify it meets minimum specs.

Usage: python3 nixos_migration_calc.py [--json] --display-class CLASS --display-resolution WxH
"""

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

MIN_RAM_MB = 1800  # 2GB Pi reports ~1849MB due to GPU memory reservation
MIN_SD_GB = 16
REQUIRED_MODEL = "Raspberry Pi 4"
# Must match the initramfs progress renderer, not just the main PiFinder UI.
SUPPORTED_DISPLAYS = {
    "DisplaySSD1351": "128x128",
    "DisplaySSD1333": "176x176",
}
# The initramfs script hardcodes these paths and unconditionally extends
# partition 2 to fill the disk. Migration only supports the stock layout.
SD_DISK = "/dev/mmcblk0"
EXPECTED_BOOT = "/dev/mmcblk0p1"
EXPECTED_ROOT = "/dev/mmcblk0p2"
EXPECTED_PARTITION_COUNT = 2


def get_model() -> str:
    """Read Pi model from device-tree."""
    try:
        return Path("/proc/device-tree/model").read_text().rstrip("\x00").strip()
    except OSError:
        return "Unknown"


def get_ram_mb() -> int:
    """Get total RAM in MB from /proc/meminfo."""
    try:
        text = Path("/proc/meminfo").read_text()
        match = re.search(r"MemTotal:\s+(\d+)\s+kB", text)
        if match:
            return int(match.group(1)) // 1024
    except OSError:
        pass
    return 0


def get_sd_size_gb() -> float:
    """Get SD card size in GB (root device)."""
    try:
        result = subprocess.run(
            ["lsblk", "-b", "-d", "-n", "-o", "SIZE", "/dev/mmcblk0"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return int(result.stdout.strip()) / (1024**3)
    except (OSError, ValueError):
        pass
    return 0.0


def get_free_space_gb(path: str = "/home/pifinder") -> float:
    """Get free space in GB at the given path."""
    try:
        usage = shutil.disk_usage(path)
        return usage.free / (1024**3)
    except OSError:
        return 0.0


def get_root_source() -> str:
    """Device backing the / mount, e.g. /dev/mmcblk0p2."""
    try:
        result = subprocess.run(
            ["findmnt", "-no", "SOURCE", "/"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except OSError:
        pass
    return ""


def get_partition_count(disk: str = SD_DISK) -> int:
    """Number of partitions on the SD disk node (excludes the disk itself)."""
    try:
        result = subprocess.run(
            ["lsblk", "-no", "NAME", "-l", disk],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return 0
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        return max(len(lines) - 1, 0)
    except OSError:
        return 0


def get_wifi_mode() -> str:
    """Detect WiFi mode."""
    wifi_status = Path("/home/pifinder/PiFinder/wifi_status.txt")
    try:
        return wifi_status.read_text().strip()
    except OSError:
        return "Unknown"


def normalize_resolution(value: str) -> str:
    """Normalize a live UI resolution string to WIDTHxHEIGHT."""
    match = re.fullmatch(r"\s*(\d+)\s*[x,]\s*(\d+)\s*", value)
    if not match:
        return value.strip()
    return f"{int(match.group(1))}x{int(match.group(2))}"


def is_pi4() -> bool:
    """Check if running on a Raspberry Pi 4."""
    model = get_model()
    return REQUIRED_MODEL in model


def check_all(display_class: str = "", display_resolution: str = "") -> dict:
    """Run all pre-flight checks. Returns dict with results."""
    model = get_model()
    ram_mb = get_ram_mb()
    sd_gb = get_sd_size_gb()
    free_gb = get_free_space_gb()
    wifi = get_wifi_mode()
    display_class = display_class.strip() or "Unknown"
    display_resolution = normalize_resolution(display_resolution) or "Unknown"
    display_ok = SUPPORTED_DISPLAYS.get(display_class) == display_resolution
    display_ok = display_ok or (
        "SSD1333" in display_class and display_resolution == "176x176"
    )
    root_source = get_root_source()
    partition_count = get_partition_count()
    boot_present = Path(EXPECTED_BOOT).is_block_device()
    layout_ok = (
        root_source == EXPECTED_ROOT
        and boot_present
        and partition_count == EXPECTED_PARTITION_COUNT
    )

    checks = {
        "model": model,
        "is_pi4": REQUIRED_MODEL in model,
        "ram_mb": ram_mb,
        "ram_ok": ram_mb >= MIN_RAM_MB,
        "sd_gb": round(sd_gb, 1),
        "sd_ok": sd_gb >= MIN_SD_GB,
        "free_gb": round(free_gb, 1),
        "free_ok": free_gb >= 1.5,
        "wifi_mode": wifi,
        "wifi_ok": wifi == "Client",
        "display_class": display_class,
        "display_resolution": display_resolution,
        "display_ok": display_ok,
        "root_source": root_source,
        "partition_count": partition_count,
        "boot_present": boot_present,
        "layout_ok": layout_ok,
        "arch": platform.machine(),
    }
    checks["all_ok"] = all(
        [
            checks["is_pi4"],
            checks["ram_ok"],
            checks["sd_ok"],
            checks["free_ok"],
            checks["wifi_ok"],
            checks["display_ok"],
            checks["layout_ok"],
        ]
    )
    return checks


def main():
    parser = argparse.ArgumentParser(description="NixOS migration pre-flight checks")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--display-class",
        default="",
        help="Live PiFinder display class name from the running UI",
    )
    parser.add_argument(
        "--display-resolution",
        default="",
        help="Live PiFinder logical display resolution as WIDTHxHEIGHT",
    )
    args = parser.parse_args()

    checks = check_all(args.display_class, args.display_resolution)

    if args.json:
        print(json.dumps(checks, indent=2))
        sys.exit(0 if checks["all_ok"] else 1)

    print(f"Model:      {checks['model']}")
    print(f"  Pi 4:     {'OK' if checks['is_pi4'] else 'FAIL'}")
    print(f"RAM:        {checks['ram_mb']} MB")
    print(f"  >= {MIN_RAM_MB}MB: {'OK' if checks['ram_ok'] else 'FAIL'}")
    print(f"SD Card:    {checks['sd_gb']} GB")
    print(f"  >= {MIN_SD_GB}GB:  {'OK' if checks['sd_ok'] else 'FAIL'}")
    print(f"Free Space: {checks['free_gb']} GB")
    print(f"  >= 1.5GB: {'OK' if checks['free_ok'] else 'FAIL'}")
    print(f"WiFi Mode:  {checks['wifi_mode']}")
    print(f"  Client:   {'OK' if checks['wifi_ok'] else 'FAIL'}")
    print(f"Display:    {checks['display_class']} {checks['display_resolution']}")
    print(
        f"  initramfs renderer supported: "
        f"{'OK' if checks['display_ok'] else 'FAIL'}"
    )
    print(f"Root:       {checks['root_source'] or 'Unknown'}")
    print(f"Partitions: {checks['partition_count']} on {SD_DISK}")
    print(
        f"  stock SD layout ({EXPECTED_BOOT} + {EXPECTED_ROOT}, 2 partitions): "
        f"{'OK' if checks['layout_ok'] else 'FAIL'}"
    )
    print(f"Arch:       {checks['arch']}")
    print()
    if checks["all_ok"]:
        print("All checks PASSED - migration can proceed")
    else:
        print("Some checks FAILED - migration cannot proceed")

    sys.exit(0 if checks["all_ok"] else 1)


if __name__ == "__main__":
    main()
