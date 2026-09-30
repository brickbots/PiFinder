{ pkgs }:
# U-Boot for booting a PiFinder from the SD card (ADR 0038): no PCI, USB or
# network probe, straight to extlinux.conf on the btrfs root.
#
# Boot counter: U-Boot keeps a 4-byte file, pifinder.bootcount, on the FAT
# FIRMWARE partition (magic 0xbd, version 1, count, upgrade_available).
# Linux sets upgrade_available=1 when it installs a trial generation. U-Boot
# then counts each boot; when the count passes bootlimit (3), it runs
# altbootcmd instead of bootcmd. altbootcmd imports pifinder-fallback.env from
# the same partition, which holds the extlinux label of the previous
# generation as pxe_label_override, and boots that label. The watchdog resets
# the file to upgrade_available=0 when a boot is healthy. With
# upgrade_available=0, U-Boot neither counts nor writes. An older U-Boot does
# not read the file.
let
  bootcmd = "sysboot mmc 0:2 any 0x02400000 /boot/extlinux/extlinux.conf";
  altbootcmd = builtins.concatStringsSep "; " [
    "echo PiFinder: boot limit reached, booting the previous generation"
    "if load mmc 0:1 \${scriptaddr} pifinder-fallback.env"
    "then env import -t \${scriptaddr} \${filesize}"
    "fi"
    "run bootcmd"
  ];
in
pkgs.ubootRaspberryPi4_64bit.override {
  extraConfig = ''
    CONFIG_CMD_PXE=y
    CONFIG_CMD_SYSBOOT=y
    CONFIG_BOOTDELAY=0
    CONFIG_PREBOOT=""
    CONFIG_BOOTCOMMAND="${bootcmd}"
    CONFIG_FS_BTRFS=y
    CONFIG_CMD_BTRFS=y
    CONFIG_PCI=n
    CONFIG_USB=n
    CONFIG_CMD_USB=n
    CONFIG_CMD_PCI=n
    CONFIG_USB_KEYBOARD=n
    CONFIG_BCMGENET=n
    CONFIG_BOOTCOUNT_LIMIT=y
    CONFIG_BOOTCOUNT_FS=y
    CONFIG_SYS_BOOTCOUNT_FS_INTERFACE="mmc"
    CONFIG_SYS_BOOTCOUNT_FS_DEVPART="0:1"
    CONFIG_SYS_BOOTCOUNT_FS_NAME="pifinder.bootcount"
    CONFIG_SYS_BOOTCOUNT_ADDR=0x05400000
    CONFIG_BOOTCOUNT_BOOTLIMIT=3
    CONFIG_BOOTCOUNT_ALTBOOTCMD="${altbootcmd}"
  '';
}
