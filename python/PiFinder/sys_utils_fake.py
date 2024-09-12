import socket
import logging

BACKUP_PATH = "/home/pifinder/PiFinder_data/PiFinder_backup.zip"

logger = logging.getLogger("SysUtils.Fake")


class Network:
    """
    Provides wifi network info
    """

    def __init__(self):
        pass

    def populate_wifi_networks(self):
        """
        Parses wpa_supplicant.conf to get current config
        """
        pass

    def get_wifi_networks(self):
        return ""

    def delete_wifi_network(self, network_id):
        """
        Immediately deletes a wifi network
        """
        pass

    def add_wifi_network(self, ssid, key_mgmt, psk=None):
        """
        Add a wifi network
        """
        pass

    def get_ap_name(self):
        return "UNKN"

    def set_ap_name(self, ap_name):
        pass

    def get_host_name(self):
        return socket.gethostname()

    def get_connected_ssid(self):
        """
        Returns the SSID of the connected wifi network or
        None if not connected or in AP mode
        """
        return "UNKN"

    def set_host_name(self, hostname):
        if hostname == self.get_host_name():
            return

    def wifi_mode(self):
        return "UNKN"

    def set_wifi_mode(self, mode):
        pass

    def local_ip(self):
        return "NONE"


def remove_backup():
    """
    Removes backup file
    """
    pass


def backup_userdata():
    """
    Back up userdata to a single zip file for later
    restore.  Returns the path to the zip file.

    Backs up:
        config.json
        observations.db
        obslist/*
    """
    return BACKUP_PATH


def restore_userdata(zip_path):
    """
    Compliment to backup_userdata
    restores userdata
    OVERWRITES existing data!
    """
    pass


def shutdown():
    """
    shuts down the Pi
    """
    logger.info("SYS: Initiating Shutdown")
    return True


def update_software():
    """
    Uses systemctl to git pull and then restart
    service
    """
    logger.info("SYS: Running update")
    return True


def restart_pifinder():
    """
    Uses systemctl to restart the PiFinder
    service
    """
    logger.info("SYS: Restarting PiFinder")
    return True


def restart_system():
    """
    Restarts the system
    """
    logger.info("SYS: Initiating System Restart")


def go_wifi_ap():
    logger.info("SYS: Switching to AP")
    return True


def go_wifi_cli():
    logger.info("SYS: Switching to Client")
    return True


def verify_password(username, password):
    """
    Checks the provided password against the provided user
    password
    """
    return True


def change_password(username, current_password, new_password):
    """
    Changes the PiFinder User password
    """
    return False


def switch_cam_imx477() -> None:
    logger.info("SYS: Switching cam to imx477")
    logger.info('sh.sudo("python", "-m", "PiFinder.switch_camera", "imx477")')


def switch_cam_imx296() -> None:
    logger.info("SYS: Switching cam to imx296")
    logger.info('sh.sudo("python", "-m", "PiFinder.switch_camera", "imx296")')
