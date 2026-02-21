import logging

from PiFinder.sys_utils_base import (
    NetworkBase,
    BACKUP_PATH,
)

logger = logging.getLogger("SysUtils.Fake")


class Network(NetworkBase):
    """
    Fake network for testing/development.
    """

    def __init__(self):
        self._wifi_mode = "Client"
        self._wifi_networks: list = []

    def populate_wifi_networks(self) -> None:
        pass

    def delete_wifi_network(self, network_id) -> None:
        pass

    def add_wifi_network(self, ssid, key_mgmt, psk=None) -> None:
        pass

    def get_ap_name(self) -> str:
        return "UNKN"

    def set_ap_name(self, ap_name: str) -> None:
        pass

    def get_connected_ssid(self) -> str:
        return "UNKN"

    def set_host_name(self, hostname: str) -> None:
        pass

    def _go_ap(self) -> None:
        logger.info("SYS: Fake switching to AP")

    def _go_client(self) -> None:
        logger.info("SYS: Fake switching to Client")


def remove_backup() -> None:
    pass


def backup_userdata() -> str:
    return BACKUP_PATH


def restore_userdata(zip_path) -> None:
    pass


def shutdown() -> None:
    logger.info("SYS: Initiating Shutdown")


def update_software(ref: str = "release"):
    logger.info("SYS: Running update (ref=%s)", ref)
    return True


def get_upgrade_progress() -> dict:
    return {"phase": "", "done": 0, "total": 0, "percent": 0}


def restart_pifinder() -> None:
    logger.info("SYS: Restarting PiFinder")


def restart_system() -> None:
    logger.info("SYS: Initiating System Restart")


def go_wifi_ap():
    logger.info("SYS: Switching to AP")
    return True


def go_wifi_cli():
    logger.info("SYS: Switching to Client")
    return True


def verify_password(username, password):
    return True


def change_password(username, current_password, new_password):
    return False


def get_camera_type() -> list[str]:
    return ["imx462"]


def switch_cam_imx477() -> None:
    logger.info("SYS: Switching cam to imx477")


def switch_cam_imx296() -> None:
    logger.info("SYS: Switching cam to imx296")


def switch_cam_imx462() -> None:
    logger.info("SYS: Switching cam to imx462")


def check_and_sync_gpsd_config(baud_rate: int) -> bool:
    logger.info("SYS: Checking GPSD config for baud rate %d (fake)", baud_rate)
    return False


def update_gpsd_config(baud_rate: int) -> None:
    logger.info("SYS: Updating GPSD config with baud rate %d (fake)", baud_rate)
