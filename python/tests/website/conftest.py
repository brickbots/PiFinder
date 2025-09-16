import pytest
import os
import requests
from selenium.webdriver.chrome.options import Options
from selenium import webdriver
from web_test_utils import get_homepage_url

@pytest.fixture(scope="session")
def shared_driver():
    """Setup Chrome driver using Selenium Grid - configurable via environment with auto-skip if unavailable"""
    # Get Selenium Grid URL from environment variable with fallback
    selenium_grid_url = os.environ.get(
        "SELENIUM_GRID_URL", "http://localhost:4444/wd/hub"
    )

    # Test if Selenium Grid is available
    try:
        status_url = selenium_grid_url.replace("/wd/hub", "/status")
        response = requests.get(status_url, timeout=5)
        if response.status_code != 200:
            pytest.skip(
                "Selenium Grid not available - tests require running Selenium Grid"
            )
    except requests.RequestException:
        pytest.skip("Selenium Grid not available - tests require running Selenium Grid")

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    try:
        driver = webdriver.Remote(
            command_executor=selenium_grid_url, options=chrome_options
        )
    except Exception as e:
        pytest.skip(f"Failed to connect to Selenium Grid at {selenium_grid_url}: {e}")

    # Ensure desktop viewport
    driver.set_window_size(1920, 1080)
    yield driver
    try:
        driver.quit()
    except Exception:
        pass  # Ignore errors on shutdown


@pytest.fixture
def driver(shared_driver):
    """Provide access to shared driver with cleanup between tests"""
    # Reset to known state before each test
    shared_driver.delete_all_cookies()
    shared_driver.set_window_size(1920, 1080)
    yield shared_driver

