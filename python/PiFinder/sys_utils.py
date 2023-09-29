import sh


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
    sh.bash("$HOME/PiFinder/pifinder_update.sh")
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
    sh.sudo("$HOME/PiFinder/switch-ap.sh")
    return True


def go_wifi_cli():
    print("SYS: Switching to Client")
    sh.sudo("$HOME/PiFinder/switch-cli.sh")
    return True
