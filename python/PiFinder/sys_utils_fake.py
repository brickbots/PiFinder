import socket
import logging
import os
import zipfile
import tempfile

# For testing, use a directory structure that mimics the production setup
# but in a writable location. The server serves from /home/pifinder/PiFinder_data
# so we need to create a backup file that can be served from there.
# Since we can't write to /home/pifinder as a regular user, we'll use the current
# user's directory structure that mirrors the production layout.
_pifinder_data_dir = os.path.expanduser("~/PiFinder_data")
os.makedirs(_pifinder_data_dir, exist_ok=True)
BACKUP_PATH = os.path.join(_pifinder_data_dir, "PiFinder_backup.zip")

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
    try:
        if os.path.exists(BACKUP_PATH):
            os.remove(BACKUP_PATH)
    except OSError:
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
    remove_backup()

    # Use actual files from ~/PiFinder_data directory
    source_dir = _pifinder_data_dir

    # Create zip file with actual user data
    with zipfile.ZipFile(BACKUP_PATH, "w", zipfile.ZIP_DEFLATED) as zipf:
        # Add config.json if it exists
        config_path = os.path.join(source_dir, "config.json")
        if os.path.exists(config_path):
            zipf.write(config_path, "home/pifinder/PiFinder_data/config.json")

        # Add observations.db if it exists
        db_path = os.path.join(source_dir, "observations.db")
        if os.path.exists(db_path):
            zipf.write(db_path, "home/pifinder/PiFinder_data/observations.db")

        # Add all files from obslists directory if it exists
        obslists_dir = os.path.join(source_dir, "obslists")
        if os.path.exists(obslists_dir):
            for filename in os.listdir(obslists_dir):
                file_path = os.path.join(obslists_dir, filename)
                if os.path.isfile(file_path):
                    zipf.write(
                        file_path, f"home/pifinder/PiFinder_data/obslists/{filename}"
                    )

    return BACKUP_PATH


def restore_userdata(zip_path):
    """
    Compliment to backup_userdata
    "restores" userdata

    For the fake version, this compares the zip contents
    with the current ~/PiFinder_data contents and throws
    an exception if they don't match.
    """
    import zipfile
    import filecmp

    if not os.path.exists(zip_path):
        raise FileNotFoundError(f"Backup file not found: {zip_path}")

    # Extract zip to temporary directory for comparison
    with tempfile.TemporaryDirectory() as temp_dir:
        with zipfile.ZipFile(zip_path, "r") as zipf:
            # Extract all files
            zipf.extractall(temp_dir)

        # Compare extracted files with actual files in ~/PiFinder_data
        extracted_base = os.path.join(temp_dir, "home", "pifinder", "PiFinder_data")
        actual_base = _pifinder_data_dir

        if not os.path.exists(extracted_base):
            raise ValueError(
                "Invalid backup file: missing expected directory structure"
            )

        # Check each file that should exist
        files_to_check = ["config.json", "observations.db"]

        for filename in files_to_check:
            extracted_file = os.path.join(extracted_base, filename)
            actual_file = os.path.join(actual_base, filename)

            # If file exists in backup but not in actual directory
            if os.path.exists(extracted_file) and not os.path.exists(actual_file):
                raise ValueError(
                    f"Backup contains {filename} but it doesn't exist in {actual_base}"
                )

            # If file exists in both, compare contents
            if os.path.exists(extracted_file) and os.path.exists(actual_file):
                if not filecmp.cmp(extracted_file, actual_file, shallow=False):
                    raise ValueError(
                        f"Backup file {filename} differs from current version in {actual_base}"
                    )

        # Check obslists directory
        extracted_obslists = os.path.join(extracted_base, "obslists")
        actual_obslists = os.path.join(actual_base, "obslists")

        if os.path.exists(extracted_obslists):
            if not os.path.exists(actual_obslists):
                raise ValueError(
                    "Backup contains obslists directory but it doesn't exist in current data"
                )

            # Compare each file in obslists
            for filename in os.listdir(extracted_obslists):
                extracted_obslist = os.path.join(extracted_obslists, filename)
                actual_obslist = os.path.join(actual_obslists, filename)

                if os.path.isfile(extracted_obslist):
                    if not os.path.exists(actual_obslist):
                        raise ValueError(
                            f"Backup contains obslist {filename} but it doesn't exist in current obslists"
                        )

                    if not filecmp.cmp(
                        extracted_obslist, actual_obslist, shallow=False
                    ):
                        raise ValueError(
                            f"Backup obslist {filename} differs from current version"
                        )

        # If we get here, all files match
        logger.info("Restore validation successful: backup contents match current data")
        return True


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
