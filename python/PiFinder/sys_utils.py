import sh


def shutdown():
    """
    shuts down the Pi
    """
    print("SYS: Initiating Shutdown")
    sh.sudo("shutdown", "now")
    return True


def restart_pifinder():
    """
    Uses systemctl to restart the PiFinder
    service
    """
    print("SYS: Restarting PiFinder")
    sh.sudo("systemctl", "restart", "pifinder")
    return True
