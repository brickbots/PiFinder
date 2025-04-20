import glob
import re
import random
import string
from typing import Dict, Any

import sh
from sh import wpa_cli, unzip, su, passwd

import socket
from PiFinder import utils
import logging

BACKUP_PATH = "/home/pifinder/PiFinder_data/PiFinder_backup.zip"
NO_PASSWORD_DEFINED = "<no password defined>"

logger = logging.getLogger()


class Network:
    """
    Provides wifi network info
    """

    def __init__(self):
        self.wifi_txt = f"{utils.pifinder_dir}/wifi_status.txt"
        self._wifi_mode = Network.get_wifi_mode()

        self.populate_wifi_networks()
        self.populate_wifi_countries()

    @staticmethod
    def get_wifi_mode():
        with open("/home/pifinder/PiFinder/wifi_status.txt", "r") as wifi_f:
            return wifi_f.read()
        
    @staticmethod
    def configure_accesspoint() -> None:
        """Add WPA2 encryption, if not already enabled.

        Tasks:
            0) If passphrase is already in hostapd.conf, do not change it (this ignores the case where the ap_name contains ENCRYPTME)
            1) if SSID in current config contains CHANGEME, create a random SSID of the from PiFinder-XYZAB, XYZAB 5 random chars (see below) and use that.
            2) If SSID in current config contains ENCRYPTME, add encryption to hostapd.conf, generate a 20 character random password
            (20 chars in 5 groups of random chars, separeted by '-', see below) 

        where 'random char' means a randomly selected character out of the set of 0-9, a-z and A-Z.
        """
        action_needed = False
        with open("/etc/hostapd/hostapd.conf", "r") as conf:
            for line in conf:
                if line.startswith("ssid="):
                    if ("ENCRYPTME" in line or "CHANGEME" in line)):
                        action_needed = True
        if not action_needed:
            return 
        
        logger.info("SYSUTILS: Configuring WIFI Access Point definition.")

        passphrase_detected = False
        ssid_changed = False
        encryption_needed = False
        with open("/tmp/hostapd.conf", "w") as new_conf:
            with open("/etc/hostapd/hostapd.conf", "r") as conf:
                for line in conf:
                    if line.startswith("ssid=") and "CHANGEME" in line:
                        ap_rnd = Network._generate_random_chars(5)
                        line = f"ssid=PiFinder-{ap_rnd}\n"
                        ssid_changed = True
                        logger.warning(f"SYS-Network: Changing SSID to 'PiFinder-{ap_rnd}'")
                    elif line.startswith("ssid=") and "ENCRYPTME" in line:
                        encryption_needed = True
                    elif line.startswith("wpa_passphrase="):
                        passphrase_detected = True
                    new_conf.write(line)
                # consumed all lines, so:
                if encryption_needed and not passphrase_detected:
                    # Do not change password, if passphrase was detected
                    logger.warning("SYS-Network: Enabling WPA2 with PSK")
                    # Add encrpytion directives
                    pwd = Network._generate_random_chars(20, "-", 5)
                    new_conf.write("wpa=2\n")
                    new_conf.write("wpa_key_mgmt=WPA-PSK\n")
                    new_conf.write(f"wpa_passphrase={pwd}\n")
                    new_conf.write("rsn_pairwise=CCMP\n")
        # Backup and move new file into place, restart service.
        logger.warning("Network: Changing configuration for hostapd")
        sh.sudo("cp", "/etc/hostapd/hostapd.conf", "/etc/hostapd/hostapd.conf.bck")
        sh.sudo("cp", "/tmp/hostapd.conf", "/etc/hostapd/hostapd.conf")
        # If we are enabling encryption or changed SSID, restart hostapd, if in AP mode
        if (not (passphrase_detected and encryption_needed) or ssid_changed) and Network.get_wifi_mode() == "AP":
                logger.warning("Network: Restarting hostapd")
                sh.sudo("systemctl", "restart", "hostapd")

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

    def populate_wifi_countries(self) -> None:
        """
        Read country codes from iso3166.tabs
        """
        try:
            with open("/usr/share/zoneinfo/iso3166.tab", "r") as iso_countries:
                lines = iso_countries.readlines()
                lines = [line for line in lines if not line.startswith("#") and line != "\n" and line != "\t\n"]
                self.COUNTRY_CODES = [line.split("\t")[0] for line in lines]
                logger.debug(f"Country Codes: {self.COUNTRY_CODES}")
                # print(self.COUNTRY_CODES)
        except IOError as e:
            logger.error("Error reading /usr/share/zoneinfo/iso3166.tab", exc_info=True)
            self.COUNTRY_CODES = ['US', 'CA', 'GB', 'DE', 'FR', 'IT', 'ES', 'NL', 'JP', 'CN']
            logger.error(f"Using default country codes: {self.COUNTRY_CODES}")

    @staticmethod
    def _generate_random_chars(length: int, ch: str = "", group: int = -1) -> str:
        """Generate a string using random characters from the set of 0-9,a-z and A-Z"""
        rndstr = "".join(
            [
                random.SystemRandom().choice(string.ascii_letters + string.digits)
                for _ in range(length)
            ]
        )
        if ch != "" and group > 0:
            rndstr = ch.join(
                [rndstr[i : i + group] for i in range(0, len(rndstr), group)]
            )
        return rndstr

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

    def get_ap_pwd(self):
        with open("/etc/hostapd/hostapd.conf", "r") as conf:
            for line in conf:
                if line.startswith("wpa_passphrase="):
                    return line[15:-1]
        return NO_PASSWORD_DEFINED 

    def set_ap_pwd(self, ap_pwd):
        """ Set Access Point password. 

        If the password is the same as the current password, nothing is done.

        If the password is NO_PASSWORD_DEFINED we consider the Access Point as open and enable encryption as a result of calling this method.
        It is the responsiblity of the caller to ensure that this method is only called when the AP needs to be encrypted.

        This method throws an ValueError of the password is < 8 or > 63 characters long.
        """
        current_pwd = self.get_ap_pwd()
        if ap_pwd == current_pwd:
            return
        
        # Enable encryption, if needed
        if current_pwd == NO_PASSWORD_DEFINED:
            ap_name = self.get_ap_name()
            self.set_ap_name(ap_name + "ENCRYPTME") 
            Network.configure_accesspoint()
            self.set_ap_name(ap_name)

        # Check password length
        if len(ap_pwd) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if len(ap_pwd) > 63:
            raise ValueError("Password must be at most 63 characters long")

        # Change password
        with open("/tmp/hostapd.conf", "w") as new_conf:
            with open("/etc/hostapd/hostapd.conf", "r") as conf:
                for line in conf:
                    if line.startswith("wpa_passphrase="):
                        line = f"wpa_passphrase={ap_pwd}\n"
                    new_conf.write(line)
        sh.sudo("cp", "/tmp/hostapd.conf", "/etc/hostapd/hostapd.conf")

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

    def get_ap_wifi_country(self):
        with open("/etc/hostapd/hostapd.conf", "r") as conf:
            for line in conf:
                if line.startswith("country_code="):
                    return line[13:-1]
        return "US"
    
    def set_ap_wifi_country(self, country_code):
        country_changed = False
        with open("/tmp/hostapd.conf", "w") as new_conf:
            no_country = True
            with open("/etc/hostapd/hostapd.conf", "r") as conf:
                for line in conf:
                    if line.startswith("country_code="):
                        line = f"country_code={country_code}\n"
                        no_country = False
                        country_changed = True
                    new_conf.write(line)
            if no_country:
                new_conf.write(f"country_code={country_code}\n")
        if country_changed:
            try:
                sh.sudo("raspi-config", "nonint", "do_wifi_country", country_code)
                sh.sudo("cp", "/tmp/hostapd.conf", "/etc/hostapd/hostapd.conf")
            except: 
                logger.warning(f"SYS: Failed to set wifi country code to {country_code}")
                raise

    def get_host_name(self):
        return socket.gethostname()

    def is_ap_open(self):
        with open("/etc/hostapd/hostapd.conf", "r") as conf:
            for line in conf:
                if line.startswith("wpa="):
                    return False
        return True

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

if __name__ == "__main__":
    # This is for testing purposes only
    network = Network()
    print(network.COUNTRY_CODES)