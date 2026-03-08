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
