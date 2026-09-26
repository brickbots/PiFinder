"""Tests for nixos/pkgs/check-root-mountable.sh (the first-boot root check)."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / "nixos" / "pkgs" / "check-root-mountable.sh"
)


def _run(tmp_path, fstab_root_line, mounts_text):
    system = tmp_path / "system"
    (system / "etc").mkdir(parents=True)
    (system / "etc" / "fstab").write_text(
        "# comment\n"
        + fstab_root_line
        + "\n/dev/disk/by-label/FIRMWARE /boot/firmware vfat defaults 0 2\n"
    )
    mounts = tmp_path / "mounts"
    mounts.write_text(mounts_text)
    return subprocess.run(
        ["bash", str(SCRIPT), str(system)],
        env={**os.environ, "MOUNTS_FILE": str(mounts)},
        capture_output=True,
        text=True,
    )


@pytest.mark.unit
def test_accepts_the_mounted_device_and_type(tmp_path):
    disk = tmp_path / "mmcblk0p2"
    disk.touch()
    result = _run(
        tmp_path,
        f"{disk} / btrfs x-initrd.mount,compress=zstd:1,noatime 0 0",
        f"rootfs / rootfs rw 0 0\n{disk} / btrfs rw,noatime 0 0\n",
    )
    assert result.returncode == 0, result.stdout


@pytest.mark.unit
def test_accepts_type_auto(tmp_path):
    disk = tmp_path / "mmcblk0p2"
    disk.touch()
    result = _run(
        tmp_path, f"{disk} / auto x-initrd.mount 0 1", f"{disk} / btrfs rw 0 0\n"
    )
    assert result.returncode == 0, result.stdout


@pytest.mark.unit
def test_accepts_a_label_that_resolves_to_the_mounted_device(tmp_path):
    disk = tmp_path / "mmcblk0p2"
    disk.touch()
    label = tmp_path / "PIFINDER_SD"
    label.symlink_to(disk)
    result = _run(tmp_path, f"{label} / btrfs defaults 0 0", f"{disk} / btrfs rw 0 0\n")
    assert result.returncode == 0, result.stdout


@pytest.mark.unit
def test_rejects_a_label_the_card_does_not_have(tmp_path):
    disk = tmp_path / "mmcblk0p2"
    disk.touch()
    result = _run(
        tmp_path,
        f"{tmp_path}/by-label/NIXOS_SD / ext4 x-initrd.mount 0 1",
        f"{disk} / btrfs rw 0 0\n",
    )
    assert result.returncode == 1
    assert "mounts / from" in result.stdout


@pytest.mark.unit
def test_rejects_another_fs_type(tmp_path):
    disk = tmp_path / "mmcblk0p2"
    disk.touch()
    result = _run(tmp_path, f"{disk} / ext4 defaults 0 1", f"{disk} / btrfs rw 0 0\n")
    assert result.returncode == 1
    assert "as ext4" in result.stdout


@pytest.mark.unit
def test_rejects_a_system_without_a_root_line(tmp_path):
    disk = tmp_path / "mmcblk0p2"
    disk.touch()
    result = _run(tmp_path, "# no root here", f"{disk} / btrfs rw 0 0\n")
    assert result.returncode == 1
    assert "no root file system" in result.stdout
