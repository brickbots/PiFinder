import pytest
import os
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.safari.options import Options as SafariOptions
from selenium.common.exceptions import InvalidSessionIdException
from web_test_utils import get_homepage_url


def _create_local_driver(browser: str):
    """Create a local WebDriver instance for the given browser."""
    if browser == "chrome":
        options = ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--lang=en-US")
        options.add_experimental_option("prefs", {"intl.accept_languages": "en-US,en"})
        return webdriver.Chrome(options=options)
    elif browser == "firefox":
        options = FirefoxOptions()
        options.add_argument("--headless")
        return webdriver.Firefox(options=options)
    elif browser == "safari":
        # Safari does not support headless mode; safaridriver must be enabled:
        #   sudo safaridriver --enable
        options = SafariOptions()
        return webdriver.Safari(options=options)
    else:
        raise ValueError(f"Unsupported browser: {browser}")


def _create_grid_driver(selenium_grid_url: str, browser: str):
    """Create a remote WebDriver via Selenium Grid."""
    if browser == "chrome":
        options = ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--lang=en-US")
        options.add_experimental_option("prefs", {"intl.accept_languages": "en-US,en"})
    elif browser == "firefox":
        options = FirefoxOptions()
        options.add_argument("--headless")
    elif browser == "safari":
        options = SafariOptions()
    else:
        raise ValueError(f"Unsupported browser: {browser}")

    return webdriver.Remote(command_executor=selenium_grid_url, options=options)


def _check_pifinder_server():
    """Return True if the PiFinder web server is reachable."""
    try:
        requests.get(get_homepage_url(), timeout=5)
        return True
    except requests.RequestException:
        return False


def _make_driver(request):
    """Create a WebDriver using the CLI options on request.config."""
    browser = request.config.getoption("--browser")
    use_local = request.config.getoption("--local")

    if use_local:
        driver = _create_local_driver(browser)
    else:
        selenium_grid_url = os.environ.get(
            "SELENIUM_GRID_URL", "http://localhost:4444/wd/hub"
        )
        grid_available = False
        try:
            status_url = selenium_grid_url.replace("/wd/hub", "/status")
            response = requests.get(status_url, timeout=5)
            grid_available = response.status_code == 200
        except requests.RequestException:
            pass

        if grid_available:
            driver = _create_grid_driver(selenium_grid_url, browser)
        else:
            driver = _create_local_driver(browser)

    try:
        driver.set_window_size(1920, 1080)
    except Exception:
        pass  # Some drivers (e.g. Safari) may reject set_window_rect
    return driver


@pytest.fixture(scope="session")
def shared_driver(request):
    """Setup WebDriver - local or via Selenium Grid, configurable via CLI options."""
    if not _check_pifinder_server():
        pytest.skip(
            f"PiFinder web server not reachable at {get_homepage_url()} - "
            "start PiFinder before running web tests"
        )

    try:
        driver = _make_driver(request)
    except Exception as e:
        pytest.skip(f"Failed to create WebDriver: {e}")

    container = [driver]
    yield container
    try:
        container[0].quit()
    except Exception:
        pass  # Ignore errors on shutdown


@pytest.fixture
def driver(shared_driver, request):
    """Provide access to shared driver with cleanup between tests.

    If the browser session has died (e.g. Chrome crashed), the session is
    transparently recreated so that the remaining tests can continue.
    """
    current = shared_driver[0]

    # Navigate to the PiFinder homepage before deleting cookies so that
    # Safari's safaridriver clears cookies for the correct origin (localhost).
    # When called while on about:blank (no origin), safaridriver only clears
    # cookies for that origin and leaves localhost session cookies intact,
    # which causes auth state to leak between tests.
    # Fall back to about:blank if the server is unreachable.
    try:
        try:
            current.get(get_homepage_url())
        except Exception:
            try:
                current.get("about:blank")
            except Exception:
                pass
        current.delete_all_cookies()
    except InvalidSessionIdException:
        # The browser session died (e.g. Chrome crashed mid-run). Recreate it
        # so subsequent tests are not all failed by a single crash.
        try:
            current.quit()
        except Exception:
            pass
        try:
            current = _make_driver(request)
        except Exception as e:
            pytest.skip(f"Failed to recreate WebDriver after session loss: {e}")
        shared_driver[0] = current

    try:
        current.set_window_size(1920, 1080)
    except Exception:
        pass  # Some drivers may not support arbitrary window sizes
    yield current
