#!/usr/bin/python
import sys

from PiFinder.boot_config import get_boot_config_path


def switch_boot(cam_type: str) -> None:
    """
    Edit the Raspberry Pi boot config to swap camera driver.
    Must be run as root.
    """
    boot_config_path = get_boot_config_path()

    # read config.txt into a list
    with open(boot_config_path, "r") as boot_in:
        boot_lines = list(boot_in)

    # Disable any existing cams
    for i, line in enumerate(boot_lines):
        if "dtoverlay=imx" in line and not line.startswith("#"):
            boot_lines[i] = "#" + line

        if "camera_auto_detect" in line and not line.startswith("#"):
            boot_lines[i] = "#" + line

    # Look for a line for requested cam
    cam_added = False
    for i, line in enumerate(boot_lines):
        if f"dtoverlay={cam_type}" in line:
            boot_lines[i] = line[1:]
            cam_added = True

    if not cam_added:
        if cam_type in ("imx290", "imx462"):
            boot_lines.append(f"dtoverlay={cam_type},clock-frequency=74250000\n")
        else:
            boot_lines.append(f"dtoverlay={cam_type}\n")
        cam_added = True

    with open(boot_config_path, "w") as boot_out:
        for line in boot_lines:
            boot_out.write(line)


if __name__ == "__main__":
    cam_type = sys.argv[1]
    switch_boot(cam_type)
