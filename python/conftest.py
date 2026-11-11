import os

from PiFinder import sys_utils_fake, utils

# The tests never change the operating system. get_sys_utils() returns the
# real sys_utils wherever its imports work. dbus-python is in the aarch64
# environment only, so on an aarch64 host the tests would get the module that
# runs sudo, systemctl and shutdown. The fake module makes the tests the same
# on x86 and aarch64.
utils._sys_utils_module = sys_utils_fake

# Adafruit Blinka detects the board when a module does "import board". It
# knows a Raspberry Pi and a generic x86 PC, but not a generic aarch64 host
# such as a GitHub arm runner, and the import fails there. The tests use no
# real hardware, so they always run as a generic PC. A value that is already
# set wins.
os.environ.setdefault("BLINKA_FORCECHIP", "GENERIC_X86")
os.environ.setdefault("BLINKA_FORCEBOARD", "GENERIC_LINUX_PC")


def pytest_addoption(parser):
    parser.addoption(
        "--browser",
        action="store",
        default="chrome",
        choices=["chrome", "firefox", "safari"],
        help="Browser to use for web tests (default: chrome)",
    )
    parser.addoption(
        "--local",
        action="store_true",
        default=False,
        help="Use local WebDriver instead of Selenium Grid",
    )
    parser.addoption(
        "--url",
        action="store",
        default=None,
        help="Base URL of the PiFinder web server (default: http://localhost)",
    )


def pytest_configure(config):
    url = config.getoption("--url", default=None)
    if url:
        os.environ["PIFINDER_HOMEPAGE"] = url
