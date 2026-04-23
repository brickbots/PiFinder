import os


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
