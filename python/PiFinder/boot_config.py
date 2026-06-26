from pathlib import Path


def get_boot_config_path() -> Path:
    """Return the active Raspberry Pi boot config path."""
    firmware_config = Path("/boot/firmware/config.txt")
    if firmware_config.exists():
        return firmware_config
    return Path("/boot/config.txt")
