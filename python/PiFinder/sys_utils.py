import sh
from sh import iwgetid, wpa_cli
import socket
from PiFinder import utils


class Network:
    """
    Provides wifi network info
    """

    def __init__(self):
        self.wifi_txt = f"{utils.pifinder_dir}/wifi_status.txt"
        with open(self.wifi_txt, "r") as wifi_f:
            self._wifi_mode = wifi_f.read()

        self.populate_wifi_networks()

    def populate_wifi_networks(self):
        """
        Uses wpa_cli to get current network config
        """
        self._wifi_networks = []

        _net_list = wpa_cli("list_networks").split("\n")

        # skip first two lines
        for net in _net_list[2:]:
            _net = net.split()
            if len(_net) > 2:
                self._wifi_networks.append(
                    {
                        "id": _net[0],
                        "ssid": _net[1],
                        "password": None,
                        "key_mgmt": None,
                        "status": "saved",
                    }
                )

        # need to call wpa_cli for each network to get key type
        for net in self._wifi_networks:
            _output = wpa_cli("get_network", net["id"], "key_mgmt")
            net["key_mgmt"] = _output.split("\n")[-1].strip()

    def get_wifi_networks(self):
        return self._wifi_networks

    def get_ap_name(self):
        with open(f"/etc/hostapd/hostapd.conf", "r") as conf:
            for l in conf:
                if l.startswith("ssid="):
                    return l[5:-1]
        return "UNKN"

    def set_ap_name(self, ap_name):
        with open(f"/tmp/hostapd.conf", "w") as new_conf:
            with open(f"/etc/hostapd/hostapd.conf", "r") as conf:
                for l in conf:
                    if l.startswith("ssid="):
                        l = f"ssid={ap_name}\n"
                    new_conf.write(l)
        sh.sudo("cp", "/tmp/hostapd.conf", "/etc/hostapd/hostapd.conf")

    def get_host_name(self):
        return socket.gethostname()

    def get_connected_ssid(self):
        """
        Returns the SSID of the connected wifi network or
        None if not connected or in AP mode
        """
        # get output from iwgetid
        _t = iwgetid().strip()
        return _t.split(":")[-1].strip('"')

    def set_host_name(self, hostname):
        sh.sudo("hostname", hostname)

    def wifi_mode(self):
        return self._wifi_mode

    def local_ip(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.255.255.255", 1))
            ip = s.getsockname()[0]
        except:
            ip = "127.0.0.1"
        finally:
            s.close()
        return ip


def shutdown():
    """
    shuts down the Pi
    """
    print("SYS: Initiating Shutdown")
    sh.sudo("shutdown", "now")
    return True


def update_software():
    """
    Uses systemctl to git pull and then restart
    service
    """
    print("SYS: Running update")
    sh.bash("/home/pifinder/PiFinder/pifinder_update.sh")
    return True


def restart_pifinder():
    """
    Uses systemctl to restart the PiFinder
    service
    """
    print("SYS: Restarting PiFinder")
    sh.sudo("systemctl", "restart", "pifinder")
    return True


def go_wifi_ap():
    print("SYS: Switching to AP")
    sh.sudo("/home/pifinder/PiFinder/switch-ap.sh")
    return True


def go_wifi_cli():
    print("SYS: Switching to Client")
    sh.sudo("/home/pifinder/PiFinder/switch-cli.sh")
    return True
