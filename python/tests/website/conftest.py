import pytest
import os
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.safari.options import Options as SafariOptions
from web_test_utils import get_homepage_url


def _create_local_driver(browser: str):
    """Create a local WebDriver instance for the given browser."""
    if browser == "chrome":
        options = ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
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


@pytest.fixture(scope="session")
def shared_driver(request):
    """Setup WebDriver - local or via Selenium Grid, configurable via CLI options."""
    if not _check_pifinder_server():
        pytest.skip(
            f"PiFinder web server not reachable at {get_homepage_url()} - "
            "start PiFinder before running web tests"
        )

    browser = request.config.getoption("--browser")
    use_local = request.config.getoption("--local")

    if use_local:
        try:
            driver = _create_local_driver(browser)
        except Exception as e:
            pytest.skip(f"Failed to create local {browser} driver: {e}")
    else:
        selenium_grid_url = os.environ.get(
            "SELENIUM_GRID_URL", "http://localhost:4444/wd/hub"
        )
        # Check if Selenium Grid is available; fall back to local if not
        grid_available = False
        try:
            status_url = selenium_grid_url.replace("/wd/hub", "/status")
            response = requests.get(status_url, timeout=5)
            grid_available = response.status_code == 200
        except requests.RequestException:
            pass

        if grid_available:
            try:
                driver = _create_grid_driver(selenium_grid_url, browser)
            except Exception as e:
                pytest.skip(
                    f"Failed to connect to Selenium Grid at {selenium_grid_url}: {e}"
                )
        else:
            # Fall back to local driver
            try:
                driver = _create_local_driver(browser)
            except Exception as e:
                pytest.skip(
                    f"Selenium Grid unavailable and local {browser} driver failed: {e}"
                )

    try:
        driver.set_window_size(1920, 1080)
    except Exception:
        pass  # Some drivers (e.g. Safari) may reject set_window_rect
    yield driver
    try:
        driver.quit()
    except Exception:
        pass  # Ignore errors on shutdown


@pytest.fixture
def driver(shared_driver):
    """Provide access to shared driver with cleanup between tests."""
    # Navigate to the PiFinder homepage before deleting cookies so that
    # Safari's safaridriver clears cookies for the correct origin (localhost).
    # When called while on about:blank (no origin), safaridriver only clears
    # cookies for that origin and leaves localhost session cookies intact,
    # which causes auth state to leak between tests.
    # Fall back to about:blank if the server is unreachable.
    try:
        shared_driver.get(get_homepage_url())
    except Exception:
        try:
            shared_driver.get("about:blank")
        except Exception:
            pass
    shared_driver.delete_all_cookies()
    try:
        shared_driver.set_window_size(1920, 1080)
    except Exception:
        pass  # Some drivers may not support arbitrary window sizes
    yield shared_driver
