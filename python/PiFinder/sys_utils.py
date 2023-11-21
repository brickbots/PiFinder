import sh
import socket
from PiFinder import utils

class network():
    """
    Provides wifi network info
    """

    def __init__(self):
        self.wifi_txt = f"{utils.pifinder_dir}/wifi_status.txt"
        with open(self.wifi_txt, "r") as wifi_f:
            self._wifi_mode = wifi_f.read()

    def wifi_mode(self):
        return self._wifi_mode

    def local_ip(self):
        try:
            ip = socket.gethostbyname(
                socket.gethostname()
            )
        except socket.gaierror:
            ip = '0.0.0.0'

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
