#!/usr/bin/python
import sys


def switch_boot(cam_type: str) -> None:
    """
    Edit /boot/config.txt to swap camera drive
    must be run as roo
    """

    # read config.txt into a list
    with open("/boot/config.txt", "r") as boot_in:
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
        boot_lines.append(f"dtoverlay={cam_type}\n")
        cam_added = True

    with open("/boot/config.txt", "w") as boot_out:
        for line in boot_lines:
            boot_out.write(line)


if __name__ == "__main__":
    cam_type = sys.argv[1]
    switch_boot(cam_type)
