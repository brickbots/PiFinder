import glob
import sh
import socket
import re
from PiFinder import utils

SYSTEM_TYPE = "UNKN"
try:
    from sh import iwgetid, nmcli, unzip, su, passwd

    SYSTEM_TYPE = "Bookworm"
except:
    pass


class BaseSystem:
    """
    Base class for all system related functions
    """

    _backup_file_path = "/home/pifinder/PiFinder_data/PiFinder_backup.zip"

    def get_wifi_networks(self) -> list[dict[str, str]]:
        """
        Returns a list of dictionaires
        representing all defined networks
        that are eligible for auto-connection
        """
        return []

    def delete_wifi_network(self, network_UUID: str) -> bool:
        """
        Removes a wifi network config identified
        by network_UUID
        This is immediate and may cause network
        disconnect
        """
        return True

    def add_wifi_network(
        self, ssid: str, key_mgmt: str, psk: str | None = None
    ) -> str | None:
        """
        Add a wifi network to the list of networks
        for potential connection

        returns the new network_UUID
        """
        return ""

    def get_ap_name(self) -> str:
        """
        Returns the SSID of the PiFinder's
        access point
        """
        return "UNKN"

    def set_ap_name(self, ap_name: str) -> bool:
        """
        Sets the SSID of the PiFinder's
        access point
        """
        return True

    def get_host_name(self) -> str:
        """
        Returns the PiFinder's host name
        """
        return "UNKN"

    def set_host_name(self, hostname: str) -> bool:
        """
        Change the PiFinder host name
        """
        return True

    def get_connected_ssid(self) -> str | None:
        """
        Returns the SSID of the connected wifi network or
        None if not connected or in AP mode
        """
        return None

    def get_wifi_mode(self) -> str:
        """
        Returns 'Client' or 'AP' to indicate
        which wifi mode the PiFinder is in
        """
        return "Client"

    def set_wifi_mode(self, mode: str) -> bool:
        """
        Sets the wifi mode. Mode can be:
            'Client'
            'AP'
        """
        return True

    def get_local_ip(self) -> str:
        if self.get_wifi_mode() == "AP":
            return "10.10.10.1"

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.255.255.255", 1))
            ip = s.getsockname()[0]
        except:
            ip = "NONE"
        finally:
            s.close()
        return str(ip)

    def get_backup_path(self) -> str:
        """
        Returns the expected location
        of the backup file
        """
        return self._backup_file_path

    def remove_backup_file(self) -> bool:
        """
        Removes backup file
        """
        return True

    def backup_userdata(self) -> str:
        """
        Back up userdata to a single zip file for later
        restore.  Returns the path to the zip file.

        Backs up:
            config.json
            observations.db
            obslist/*
        """
        return self.get_backup_path()

    def restore_userdata(self, zip_path: str) -> bool:
        """
        Compliment to backup_userdata
        restores userdata
        OVERWRITES existing data!
        """
        return True

    def shutdown(self) -> None:
        """
        shuts down the Pi
        """
        return None

    def update_software(self) -> bool:
        """
        Uses systemctl to git pull and then restart
        service
        """
        return True

    def restart_pifinder(self) -> None:
        """
        Uses systemctl to restart the PiFinder
        service
        """
        return None

    def restart_system(self) -> None:
        """
        Restarts the system
        """
        return None

    def go_wifi_ap(self) -> bool:
        """
        Switches the network to access point mode
        """
        return True

    def go_wifi_cli(self) -> bool:
        """
        Switches the network to Client mode
        """
        return True

    def verify_password(self, username: str, password: str) -> bool:
        """
        Checks the provided password against the provided user
        password
        """
        return True

    def change_password(
        self, username: str, current_password: str, new_password: str
    ) -> bool:
        """
        Changes the PiFinder User password
        """
        return True


class PiSystem(BaseSystem):
    """
    System class for Bookwork/RPI systems
    """

    def __init__(self) -> None:
        self.wifi_txt = f"{utils.pifinder_dir}/wifi_status.txt"
        with open(self.wifi_txt, "r") as wifi_f:
            self._wifi_mode = wifi_f.read()

        self.populate_wifi_networks()

    def populate_wifi_networks(self) -> None:
        """
        Fetches all wifi networks configured
        using nmcli
        """
        self._wifi_networks = []

        connection_list = nmcli("-c=no", "-t", "c")
        for connection in connection_list.split("\n")[:-1]:
            connection_info = connection.split(":")
            if connection_info[2] == "802-11-wireless":
                connection_name = connection_info[0]
                connection_UUID = connection_info[1]
                # get all the info
                connection_details = {}
                connection_details_items = nmcli(
                    "-c=no", "-t", "c", "show", "uuid", connection_UUID
                ).split("\n")[:-1]
                for detail in connection_details_items:
                    key, value = detail.split(":")[0:2]
                    connection_details[key] = value
                network_dict = {
                    "UUID": connection_UUID,
                    "name": connection_name,
                    "ssid": connection_details["802-11-wireless.ssid"],
                    "psk": None,
                    "key_mgmt": connection_details.get(
                        "802-11-wireless-security.key-mgmt", "NONE"
                    ),
                }
                self._wifi_networks.append(network_dict)

    def get_wifi_networks(self) -> list[dict[str, str]]:
        return self._wifi_networks

    def delete_wifi_network(self, network_UUID: str) -> bool:
        """
        Immediately deletes a wifi network
        """
        try:
            sh.sudo("nmcli", "connection", "delete", "uuid", network_UUID)
        except:
            return False

        self.populate_wifi_networks()
        return True

    def add_wifi_network(
        self, ssid: str, key_mgmt: str, psk: str | None = None
    ) -> str | None:
        """
        Add a wifi network
        """
        new_network_UUID = None
        try:
            result = sh.sudo(
                "nmcli",
                "connection",
                "add",
                "type",
                "wifi",
                "ifname",
                "wlan0",
                "con-name",
                ssid,
                "ssid",
                ssid,
                "autoconnect",
                "true",
                "save",
                "yes",
                "--",
                "802-11-wireless-security.key-mgmt",
                key_mgmt,
                "802-11-wireless-security.psk",
                psk,
            )
            new_network_UUID = re.findall(r"\(.*?\)", str(result))[0][1:-1]
            self.populate_wifi_networks()
        except:
            pass
        return new_network_UUID

    def get_ap_name(self) -> str:
        with open(f"/etc/hostapd/hostapd.conf", "r") as conf:
            for l in conf:
                if l.startswith("ssid="):
                    return l[5:-1]
        return "UNKN"

    def set_ap_name(self, ap_name: str) -> bool:
        if ap_name == self.get_ap_name():
            return True
        with open(f"/tmp/hostapd.conf", "w") as new_conf:
            with open(f"/etc/hostapd/hostapd.conf", "r") as conf:
                for l in conf:
                    if l.startswith("ssid="):
                        l = f"ssid={ap_name}\n"
                    new_conf.write(l)
        sh.sudo("cp", "/tmp/hostapd.conf", "/etc/hostapd/hostapd.conf")
        return True

    def get_host_name(self) -> str:
        return socket.gethostname()

    def get_connected_ssid(self) -> str | None:
        """
        Returns the SSID of the connected wifi network or
        None if not connected or in AP mode
        """
        if self.get_wifi_mode() == "AP":
            return None
        # get output from iwgetid
        _t = iwgetid(_ok_code=(0, 255)).strip()
        return str(_t.split(":")[-1].strip('"'))

    def set_host_name(self, hostname: str) -> bool:
        if hostname == self.get_host_name():
            return True
        result = sh.sudo("hostnamectl", "set-hostname", hostname)
        return True

    def get_wifi_mode(self) -> str:
        return self._wifi_mode

    def set_wifi_mode(self, mode: str) -> bool:
        if mode == self._wifi_mode:
            return True
        if mode == "AP":
            self.go_wifi_ap()

        if mode == "Client":
            self.go_wifi_cli()

        return True

    def remove_backup_file(self) -> bool:
        """
        Removes backup file
        """
        sh.sudo("rm", self._backup_file_path, _ok_code=(0, 1))
        return True

    def backup_userdata(self) -> str:
        """
        Back up userdata to a single zip file for later
        restore.  Returns the path to the zip file.

        Backs up:
            config.json
            observations.db
            obslist/*
        """

        self.remove_backup_file()

        _zip = sh.Command("zip")
        _zip(
            self._backup_file_path,
            "/home/pifinder/PiFinder_data/config.json",
            "/home/pifinder/PiFinder_data/observations.db",
            glob.glob("/home/pifinder/PiFinder_data/obslists/*"),
        )

        return self._backup_file_path

    def restore_userdata(self, zip_path: str) -> bool:
        """
        Compliment to backup_userdata
        restores userdata
        OVERWRITES existing data!
        """
        unzip("-d", "/", "-o", zip_path)
        return True

    def shutdown(self) -> None:
        """
        shuts down the Pi
        """
        print("SYS: Initiating Shutdown")
        sh.sudo("shutdown", "now")

    def update_software(self) -> bool:
        """
        Uses systemctl to git pull and then restart
        service
        """
        print("SYS: Running update")
        sh.bash("/home/pifinder/PiFinder/pifinder_update.sh")
        return True

    def restart_pifinder(self) -> None:
        """
        Uses systemctl to restart the PiFinder
        service
        """
        print("SYS: Restarting PiFinder")
        sh.sudo("systemctl", "restart", "pifinder")

    def restart_system(self) -> None:
        """
        Restarts the system
        """
        print("SYS: Initiating System Restart")
        sh.sudo("shutdown", "-r", "now")

    def go_wifi_ap(self) -> bool:
        print("SYS: Switching to AP")
        sh.sudo("/home/pifinder/PiFinder/switch-ap.sh")
        return True

    def go_wifi_cli(self) -> bool:
        print("SYS: Switching to Client")
        sh.sudo("/home/pifinder/PiFinder/switch-cli.sh")
        return True

    def verify_password(self, username: str, password: str) -> bool:
        """
        Checks the provided password against the provided user
        password
        """
        result = su(username, "-c", "echo", _in=f"{password}\n", _ok_code=(0, 1))
        if result.exit_code == 0:
            return True
        else:
            return False

    def change_password(
        self, username: str, current_password: str, new_password: str
    ) -> bool:
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


def System() -> BaseSystem:
    if SYSTEM_TYPE == "Bookworm":
        return PiSystem()
    else:
        return BaseSystem()
