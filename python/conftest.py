import os

# Adafruit Blinka detects the board when a module does "import board". It
# knows a Raspberry Pi and a generic x86 PC, but not a generic aarch64 host
# such as a GitHub arm runner, and the import fails there. The tests use no
# real hardware, so they always run as a generic PC. A value that is already
# set wins.
os.environ.setdefault("BLINKA_FORCECHIP", "GENERIC_X86")
os.environ.setdefault("BLINKA_FORCEBOARD", "GENERIC_LINUX_PC")

# tests/test_sys_utils.py comes from upstream main. It tests the Raspbian
# sys_utils, which edits wpa_supplicant.conf and /etc/hosts. The NixOS
# sys_utils uses NetworkManager and has none of that code. The file stays
# unchanged, so merges from upstream main do not conflict.
collect_ignore = ["tests/test_sys_utils.py"]


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
