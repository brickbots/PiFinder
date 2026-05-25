#!/usr/bin/env python3
"""
Pre-flight checks for NixOS migration.

Validates hardware requirements before migration can proceed.
Run on the Pi to verify it meets minimum specs.

Usage: python3 nixos_migration_calc.py [--json]
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

MIN_RAM_MB = 1800  # 2GB Pi reports ~1849MB due to GPU memory reservation
MIN_SD_GB = 16
REQUIRED_MODEL = "Raspberry Pi 4"


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


def get_wifi_mode() -> str:
    """Detect WiFi mode."""
    wifi_status = Path("/home/pifinder/PiFinder/wifi_status.txt")
    try:
        return wifi_status.read_text().strip()
    except OSError:
        return "Unknown"


def is_pi4() -> bool:
    """Check if running on a Raspberry Pi 4."""
    model = get_model()
    return REQUIRED_MODEL in model


def check_all() -> dict:
    """Run all pre-flight checks. Returns dict with results."""
    model = get_model()
    ram_mb = get_ram_mb()
    sd_gb = get_sd_size_gb()
    free_gb = get_free_space_gb()
    wifi = get_wifi_mode()

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
        "arch": platform.machine(),
    }
    checks["all_ok"] = all(
        [checks["is_pi4"], checks["ram_ok"], checks["sd_ok"], checks["wifi_ok"]]
    )
    return checks


def main():
    parser = argparse.ArgumentParser(description="NixOS migration pre-flight checks")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    checks = check_all()

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
    print(f"WiFi Mode:  {checks['wifi_mode']}")
    print(f"  Client:   {'OK' if checks['wifi_ok'] else 'FAIL'}")
    print(f"Arch:       {checks['arch']}")
    print()
    if checks["all_ok"]:
        print("All checks PASSED - migration can proceed")
    else:
        print("Some checks FAILED - migration cannot proceed")

    sys.exit(0 if checks["all_ok"] else 1)


if __name__ == "__main__":
    main()
