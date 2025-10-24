import glob
import re
from typing import Dict, Any

import sh
from sh import wpa_cli, unzip, su, passwd

import socket
from PiFinder import utils
import logging

BACKUP_PATH = "/home/pifinder/PiFinder_data/PiFinder_backup.zip"

logger = logging.getLogger("SysUtils")


class Network:
    """
    Provides wifi network info
    """

    def __init__(self):
        self.wifi_txt = f"{utils.pifinder_dir}/wifi_status.txt"
        with open(self.wifi_txt, "r") as wifi_f:
            self._wifi_mode = wifi_f.read()

        self.populate_wifi_networks()

    def populate_wifi_networks(self) -> None:
        wpa_supplicant_path = "/etc/wpa_supplicant/wpa_supplicant.conf"
        self._wifi_networks = []
        try:
            with open(wpa_supplicant_path, "r") as wpa_conf:
                contents = wpa_conf.readlines()
        except IOError as e:
            logger.error(f"Error reading wpa_supplicant.conf: {e}")
            return

        self._wifi_networks = Network._parse_wpa_supplicant(contents)

    @staticmethod
    def _parse_wpa_supplicant(contents: list[str]) -> list:
        """
        Parses wpa_supplicant.conf to get current config
        """
        wifi_networks = []
        network_dict: Dict[str, Any] = {}
        network_id = 0
        in_network_block = False
        for line in contents:
            line = line.strip()
            if line.startswith("network={"):
                in_network_block = True
                network_dict = {
                    "id": network_id,
                    "ssid": None,
                    "psk": None,
                    "key_mgmt": None,
                }

            elif line == "}" and in_network_block:
                in_network_block = False
                wifi_networks.append(network_dict)
                network_id += 1

            elif in_network_block:
                match = re.match(r"(\w+)=(.+)", line)
                if match:
                    key, value = match.groups()
                    if key in network_dict:
                        network_dict[key] = value.strip('"')

        return wifi_networks

    def get_wifi_networks(self):
        return self._wifi_networks

    def delete_wifi_network(self, network_id):
        """
        Immediately deletes a wifi network
        """
        self._wifi_networks.pop(network_id)

        with open("/etc/wpa_supplicant/wpa_supplicant.conf", "r") as wpa_conf:
            wpa_contents = list(wpa_conf)

        with open("/etc/wpa_supplicant/wpa_supplicant.conf", "w") as wpa_conf:
            in_networks = False
            for line in wpa_contents:
                if not in_networks:
                    if line.startswith("network={"):
                        in_networks = True
                    else:
                        wpa_conf.write(line)

            for network in self._wifi_networks:
                ssid = network["ssid"]
                key_mgmt = network["key_mgmt"]
                psk = network["psk"]

                wpa_conf.write("\nnetwork={\n")
                wpa_conf.write(f'\tssid="{ssid}"\n')
                if key_mgmt == "WPA-PSK":
                    wpa_conf.write(f'\tpsk="{psk}"\n')
                wpa_conf.write(f"\tkey_mgmt={key_mgmt}\n")

                wpa_conf.write("}\n")

        self.populate_wifi_networks()

    def add_wifi_network(self, ssid, key_mgmt, psk=None):
        """
        Add a wifi network
        """
        with open("/etc/wpa_supplicant/wpa_supplicant.conf", "a") as wpa_conf:
            wpa_conf.write("\nnetwork={\n")
            wpa_conf.write(f'\tssid="{ssid}"\n')
            if key_mgmt == "WPA-PSK":
                wpa_conf.write(f'\tpsk="{psk}"\n')
            wpa_conf.write(f"\tkey_mgmt={key_mgmt}\n")

            wpa_conf.write("}\n")

        self.populate_wifi_networks()
        if self._wifi_mode == "Client":
            # Restart the supplicant
            wpa_cli("reconfigure")

    def get_ap_name(self):
        with open("/etc/hostapd/hostapd.conf", "r") as conf:
            for line in conf:
                if line.startswith("ssid="):
                    return line[5:-1]
        return "UNKN"

    def set_ap_name(self, ap_name):
        if ap_name == self.get_ap_name():
            return
        with open("/tmp/hostapd.conf", "w") as new_conf:
            with open("/etc/hostapd/hostapd.conf", "r") as conf:
                for line in conf:
                    if line.startswith("ssid="):
                        line = f"ssid={ap_name}\n"
                    new_conf.write(line)
        sh.sudo("cp", "/tmp/hostapd.conf", "/etc/hostapd/hostapd.conf")

    def get_host_name(self):
        return socket.gethostname()

    def get_connected_ssid(self) -> str:
        """
        Returns the SSID of the connected wifi network or
        None if not connected or in AP mode
        """
        if self.wifi_mode() == "AP":
            return ""
        # get output from iwgetid
        try:
            iwgetid = sh.Command("iwgetid")
            _t = iwgetid(_ok_code=(0, 255)).strip()
            return _t.split(":")[-1].strip('"')
        except sh.CommandNotFound:
            return "ssid_not_found"

    def set_host_name(self, hostname) -> None:
        if hostname == self.get_host_name():
            return
        _result = sh.sudo("hostnamectl", "set-hostname", hostname)

    def wifi_mode(self):
        return self._wifi_mode

    def set_wifi_mode(self, mode):
        if mode == self._wifi_mode:
            return
        if mode == "AP":
            go_wifi_ap()

        if mode == "Client":
            go_wifi_cli()

    def local_ip(self):
        if self._wifi_mode == "AP":
            return "10.10.10.1"

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.255.255.255", 1))
            ip = s.getsockname()[0]
        except Exception:
            ip = "NONE"
        finally:
            s.close()
        return ip


def go_wifi_ap():
    logger.info("SYS: Switching to AP")
    sh.sudo("/home/pifinder/PiFinder/switch-ap.sh")
    return True


def go_wifi_cli():
    logger.info("SYS: Switching to Client")
    sh.sudo("/home/pifinder/PiFinder/switch-cli.sh")
    return True


def remove_backup():
    """
    Removes backup file
    """
    sh.sudo("rm", BACKUP_PATH, _ok_code=(0, 1))


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

    _zip = sh.Command("zip")
    _zip(
        BACKUP_PATH,
        "/home/pifinder/PiFinder_data/config.json",
        "/home/pifinder/PiFinder_data/observations.db",
        glob.glob("/home/pifinder/PiFinder_data/obslists/*"),
    )

    return BACKUP_PATH


def restore_userdata(zip_path):
    """
    Compliment to backup_userdata
    restores userdata
    OVERWRITES existing data!
    """
    unzip("-d", "/", "-o", zip_path)


def restart_pifinder() -> None:
    """
    Uses systemctl to restart the PiFinder
    service
    """
    logger.info("SYS: Restarting PiFinder")
    sh.sudo("systemctl", "restart", "pifinder")


def restart_system() -> None:
    """
    Restarts the system
    """
    logger.info("SYS: Initiating System Restart")
    sh.sudo("shutdown", "-r", "now")


def shutdown() -> None:
    """
    shuts down the system
    """
    logger.info("SYS: Initiating Shutdown")
    sh.sudo("shutdown", "now")


def update_software():
    """
    Uses systemctl to git pull and then restart
    service
    """
    logger.info("SYS: Running update")
    sh.bash("/home/pifinder/PiFinder/pifinder_update.sh")
    return True


def verify_password(username, password):
    """
    Checks the provided password against the provided user
    password
    """
    result = su(username, "-c", "echo", _in=f"{password}\n", _ok_code=(0, 1))
    if result.exit_code == 0:
        return True
    else:
        return False


def change_password(username, current_password, new_password):
    """
    Changes the PiFinder User password
    """
    result = passwd(
        username,
        _in=f"{current_password}\n{new_password}\n{new_password}\n",
        _ok_code=(0, 10),
    )

    if result.exit_code == 0:
        return True
    else:
        return False


def switch_cam_imx477() -> None:
    logger.info("SYS: Switching cam to imx477")
    sh.sudo("python", "-m", "PiFinder.switch_camera", "imx477")


def switch_cam_imx296() -> None:
    logger.info("SYS: Switching cam to imx296")
    sh.sudo("python", "-m", "PiFinder.switch_camera", "imx296")


def switch_cam_imx462() -> None:
    logger.info("SYS: Switching cam to imx462")
    sh.sudo("python", "-m", "PiFinder.switch_camera", "imx462")


def check_and_sync_gpsd_config(baud_rate: int) -> bool:
    """
    Checks if GPSD configuration matches the desired baud rate,
    and updates it only if necessary.

    Args:
        baud_rate: The desired baud rate (9600 or 115200)

    Returns:
        True if configuration was updated, False if already correct
    """
    logger.info(f"SYS: Checking GPSD config for baud rate {baud_rate}")

    try:
        # Read current config
        with open("/etc/default/gpsd", "r") as f:
            content = f.read()

        # Determine expected GPSD_OPTIONS
        if baud_rate == 115200:
            # NOTE: the space before -s in the next line is really needed
            expected_options = 'GPSD_OPTIONS=" -s 115200"'
        else:
            expected_options = 'GPSD_OPTIONS=""'

        # Check if update is needed
        current_match = re.search(r'^GPSD_OPTIONS=.*$', content, re.MULTILINE)
        if current_match:
            current_options = current_match.group(0)
            if current_options == expected_options:
                logger.info("SYS: GPSD config already correct, no update needed")
                return False

        # Update is needed
        logger.info(f"SYS: GPSD config mismatch, updating to {expected_options}")
        update_gpsd_config(baud_rate)
        return True

    except Exception as e:
        logger.error(f"SYS: Error checking/syncing GPSD config: {e}")
        return False


def update_gpsd_config(baud_rate: int) -> None:
    """
    Updates the GPSD configuration file with the specified baud rate
    and restarts the GPSD service.

    Args:
        baud_rate: The baud rate to configure (9600 or 115200)
    """
    logger.info(f"SYS: Updating GPSD config with baud rate {baud_rate}")

    try:
        # Read the current config
        with open("/etc/default/gpsd", "r") as f:
            lines = f.readlines()

        # Update GPSD_OPTIONS line
        updated_lines = []
        for line in lines:
            if line.startswith("GPSD_OPTIONS="):
                if baud_rate == 115200:
                    # NOTE: the space before -s in the next line is really needed
                    updated_lines.append('GPSD_OPTIONS=" -s 115200"\n')
                else:
                    updated_lines.append('GPSD_OPTIONS=""\n')
            else:
                updated_lines.append(line)

        # Write the updated config to a temporary file
        with open("/tmp/gpsd.conf", "w") as f:
            f.writelines(updated_lines)

        # Copy the temp file to the actual location with sudo
        sh.sudo("cp", "/tmp/gpsd.conf", "/etc/default/gpsd")

        # Restart GPSD service
        sh.sudo("systemctl", "restart", "gpsd")

        logger.info("SYS: GPSD configuration updated and service restarted")

    except Exception as e:
        logger.error(f"SYS: Error updating GPSD config: {e}")
        raise

