import pytest
import requests
import time
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from web_test_utils import login_to_logs as util_login_to_logs, login_with_password


def login_to_logs(driver):
    """Helper function to login and navigate to logs page"""
    util_login_to_logs(driver)
    login_with_password(driver)
    # Wait for logs page to load after successful login
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "logViewer"))
    )


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
    except requests.exceptions.RequestException:
        pytest.skip("Selenium Grid not available - tests require running Selenium Grid")

    chrome_options = Options()
    # chrome_options.add_argument("--headless")  # Disabled for debugging
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Remote(
        command_executor=selenium_grid_url, options=chrome_options
    )
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


@pytest.mark.web
def test_logs_page_loads(driver):
    """Test that the logs page loads successfully"""
    login_to_logs(driver)

    # Verify page loaded successfully
    assert "PiFinder - Logs" in driver.title


@pytest.mark.web
def test_logs_page_header_present(driver):
    """Test that the logs page header is present"""
    login_to_logs(driver)

    # Look for the page header
    header = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "h5"))
    )
    assert "PiFinder Logs" in header.text


@pytest.mark.web
def test_logs_control_buttons_present(driver):
    """Test that all control buttons are present"""
    login_to_logs(driver)

    # Check for Download All Logs button
    download_btn = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "a[href='/logs/download']"))
    )
    assert "DOWNLOAD ALL LOGS" in download_btn.text.upper()

    # Check for Pause button
    pause_btn = driver.find_element(By.ID, "pauseButton")
    assert "PAUSE" in pause_btn.text.upper()

    # Check for Copy to Clipboard button
    copy_btn = driver.find_element(By.ID, "copyButton")
    assert "COPY TO CLIPBOARD" in copy_btn.text.upper()


@pytest.mark.web
def test_logs_select_dropdowns_present(driver):
    """Test that log level and component select dropdowns are present"""
    login_to_logs(driver)

    # Check for Global Level select
    global_level_select = driver.find_element(By.ID, "globalLevel")
    assert global_level_select is not None

    # Verify Global Level options
    options = global_level_select.find_elements(By.TAG_NAME, "option")
    option_texts = [opt.text for opt in options]
    assert "Global: Debug" in option_texts
    assert "Global: Info" in option_texts
    assert "Global: Warning" in option_texts
    assert "Global: Error" in option_texts

    # Check for Component Select
    component_select = driver.find_element(By.ID, "componentSelect")
    assert component_select is not None

    # Check for Component Level select (initially hidden)
    component_level_select = driver.find_element(By.ID, "componentLevel")
    assert component_level_select is not None
    # Should be hidden by default
    assert component_level_select.value_of_css_property("display") == "none"


@pytest.mark.web
def test_logs_container_and_stats_present(driver):
    """Test that log container and stats elements are present"""
    login_to_logs(driver)

    # Check for log viewer container
    log_viewer = driver.find_element(By.ID, "logViewer")
    assert log_viewer is not None

    # Check for loading message
    loading_message = driver.find_element(By.ID, "loadingMessage")
    assert "Loading log files..." in loading_message.text

    # Check for log content container
    log_content = driver.find_element(By.ID, "logContent")
    assert log_content is not None

    # Check for total lines counter
    total_lines = driver.find_element(By.ID, "totalLines")
    assert total_lines is not None
    # Should start at 0
    assert total_lines.text == "0"


@pytest.mark.web
def test_logs_hidden_buttons_present(driver):
    """Test that initially hidden control buttons are present in DOM"""
    login_to_logs(driver)

    # Check for Resume from Current button (initially hidden)
    restart_current_btn = driver.find_element(By.ID, "restartFromCurrent")
    assert restart_current_btn is not None
    # Should be hidden by default
    assert restart_current_btn.value_of_css_property("display") == "none"

    # Check for Restart from End button (initially hidden)
    restart_end_btn = driver.find_element(By.ID, "restartFromEnd")
    assert restart_end_btn is not None
    # Should be hidden by default
    assert restart_end_btn.value_of_css_property("display") == "none"


@pytest.mark.web
def test_logs_card_structure(driver):
    """Test that the main card structure is present"""
    login_to_logs(driver)

    # Check for main card
    card = driver.find_element(By.CSS_SELECTOR, ".card.grey.darken-2")
    assert card is not None

    # Check for card content
    card_content = card.find_element(By.CLASS_NAME, "card-content")
    assert card_content is not None

    # Check for controls section
    controls = card.find_element(By.CLASS_NAME, "controls")
    assert controls is not None

    # Check for log stats section
    log_stats = card.find_element(By.CLASS_NAME, "log-stats")
    assert log_stats is not None
    assert "Total lines:" in log_stats.text


@pytest.mark.web
def test_logs_responsive_classes_present(driver):
    """Test that responsive classes are applied correctly"""
    login_to_logs(driver)

    # Check for Materialize grid classes
    rows = driver.find_elements(By.CLASS_NAME, "row")
    assert len(rows) >= 2  # Should have at least header row and content row

    # Check for column classes
    cols = driver.find_elements(By.CSS_SELECTOR, ".col.s12")
    assert len(cols) >= 2  # Should have columns for header and content


# Dynamic Log Testing


@pytest.mark.web
def test_logs_stream_api_response(driver):
    """Test that /logs/stream API returns proper JSON structure"""
    try:
        # Login first to get authenticated cookies
        login_to_logs(driver)
        cookies = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}

        response = requests.get(
            "http://localhost:8080/logs/stream?position=0", cookies=cookies, timeout=10
        )
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert "position" in data
        assert isinstance(data["logs"], list)
        assert isinstance(data["position"], int)
    except requests.exceptions.RequestException:
        pytest.skip("PiFinder web server not available")


@pytest.mark.web
def test_logs_components_api_response(driver):
    """Test that /logs/components API returns proper JSON structure"""
    try:
        # Login first to get authenticated cookies
        login_to_logs(driver)
        cookies = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}

        response = requests.get(
            "http://localhost:8080/logs/components", cookies=cookies, timeout=10
        )
        assert response.status_code == 200
        data = response.json()
        assert "components" in data
        assert isinstance(data["components"], dict)
    except requests.exceptions.RequestException:
        pytest.skip("PiFinder web server not available")


@pytest.mark.web
def test_logs_auto_refresh(driver):
    """Test that logs automatically refresh and display new content"""
    login_to_logs(driver)

    # Wait for initial load
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "logContent"))
    )

    # Wait for loading message to disappear and logs to appear
    WebDriverWait(driver, 20).until(
        lambda d: d.find_element(By.ID, "loadingMessage").value_of_css_property(
            "display"
        )
        == "none"
    )

    # Wait for logs to appear (may take a few seconds)
    WebDriverWait(driver, 15).until(
        lambda d: d.find_element(By.ID, "totalLines").text != "0"
    )

    initial_count = int(driver.find_element(By.ID, "totalLines").text)
    assert initial_count > 0

    # Verify log content is present
    log_content = driver.find_element(By.ID, "logContent")
    assert log_content.text.strip() != ""


@pytest.mark.web
def test_logs_pause_resume(driver):
    """Test pause and resume functionality"""
    login_to_logs(driver)

    # Wait for logs to load
    WebDriverWait(driver, 20).until(
        lambda d: d.find_element(By.ID, "loadingMessage").value_of_css_property(
            "display"
        )
        == "none"
    )

    WebDriverWait(driver, 15).until(
        lambda d: d.find_element(By.ID, "totalLines").text != "0"
    )

    # Click pause
    pause_btn = driver.find_element(By.ID, "pauseButton")
    pause_btn.click()
    time.sleep(1)

    # Verify button text changed to Resume
    WebDriverWait(driver, 5).until(
        lambda d: "RESUME" in d.find_element(By.ID, "pauseButton").text.upper()
    )

    # Click resume
    pause_btn.click()

    # Verify button text changed back to Pause
    WebDriverWait(driver, 5).until(
        lambda d: "PAUSE" in d.find_element(By.ID, "pauseButton").text.upper()
    )


@pytest.mark.web
def test_log_level_colors(driver):
    """Test that different log levels display with correct colors"""
    login_to_logs(driver)

    # Wait for logs to load
    WebDriverWait(driver, 20).until(
        lambda d: d.find_element(By.ID, "loadingMessage").value_of_css_property(
            "display"
        )
        == "none"
    )

    WebDriverWait(driver, 15).until(
        lambda d: d.find_element(By.ID, "totalLines").text != "0"
    )

    # Wait for log lines to appear
    WebDriverWait(driver, 10).until(
        lambda d: len(d.find_elements(By.CSS_SELECTOR, "#logContent > div")) > 0
    )

    # Check for log lines
    log_lines = driver.find_elements(By.CSS_SELECTOR, "#logContent > div")
    assert len(log_lines) > 0

    # Expected colors from logs.html (lines 220-228 and CSS)
    # Note: Browsers may return colors in rgb() or rgba() format
    expected_colors = {
        "rgb(212, 212, 212)",
        "rgba(212, 212, 212, 1)",  # Default color #d4d4d4
        "rgb(255, 107, 107)",
        "rgba(255, 107, 107, 1)",  # ERROR color #ff6b6b
        "rgb(255, 217, 61)",
        "rgba(255, 217, 61, 1)",  # WARNING color #ffd93d
        "rgb(107, 255, 107)",
        "rgba(107, 255, 107, 1)",  # INFO color #6bff6b
        "rgb(107, 107, 255)",
        "rgba(107, 107, 255, 1)",  # DEBUG color #6b6bff
    }

    # Collect all colors found in log lines
    colors_found = set()
    for line in log_lines:
        try:
            color = line.value_of_css_property("color")
            colors_found.add(color)
        except Exception:
            continue

    # Verify that only expected colors are present
    unexpected_colors = colors_found - expected_colors
    assert len(unexpected_colors) == 0, f"Found unexpected colors: {unexpected_colors}"

    # Verify that at least one color is present (should have at least default)
    assert len(colors_found) > 0, "No colors found in log lines"

    # Verify that at least one expected color is present
    valid_colors_found = colors_found & expected_colors
    assert (
        len(valid_colors_found) > 0
    ), f"No expected colors found. Found: {colors_found}, Expected: {expected_colors}"


@pytest.mark.web
def test_component_level_loading(driver):
    """Test that component levels are loaded dynamically"""
    login_to_logs(driver)

    # Wait for page to load
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "componentSelect"))
    )

    # Wait for component select to be populated (may take time for API call)
    WebDriverWait(driver, 15).until(
        lambda d: len(
            d.find_element(By.ID, "componentSelect").find_elements(
                By.TAG_NAME, "option"
            )
        )
        > 1
    )
    time.sleep(0.5)  # Extra wait to ensure options are fully loaded

    component_select = driver.find_element(By.ID, "componentSelect")
    options = component_select.find_elements(By.TAG_NAME, "option")

    # Should have more than just the default "Select Component" option
    assert len(options) > 1

    # Check that options have meaningful text (not empty)
    option_texts = [opt.text for opt in options if opt.text != "Select Component"]
    assert len(option_texts) > 0
    assert all(text.strip() != "" for text in option_texts)


@pytest.mark.web
def test_component_level_selection(driver):
    """Test component level selection functionality"""
    login_to_logs(driver)

    # Wait for component select to be populated
    WebDriverWait(driver, 15).until(
        lambda d: len(
            d.find_element(By.ID, "componentSelect").find_elements(
                By.TAG_NAME, "option"
            )
        )
        > 1
    )
    time.sleep(0.5)  # Extra wait to ensure options are fully loaded

    component_select = Select(driver.find_element(By.ID, "componentSelect"))
    component_level_select = driver.find_element(By.ID, "componentLevel")

    # Initially, component level should be hidden
    assert component_level_select.value_of_css_property("display") == "none"

    # Select a component (skip the first option which is "Select Component")
    options = component_select.options
    if len(options) > 1:
        component_select.select_by_index(1)

        # Component level select should now be visible
        WebDriverWait(driver, 5).until(
            lambda d: d.find_element(By.ID, "componentLevel").value_of_css_property(
                "display"
            )
            != "none"
        )


@pytest.mark.web
def test_copy_to_clipboard_feedback(driver):
    """Test copy to clipboard visual feedback"""
    login_to_logs(driver)

    # Wait for logs to load
    WebDriverWait(driver, 20).until(
        lambda d: d.find_element(By.ID, "loadingMessage").value_of_css_property(
            "display"
        )
        == "none"
    )

    WebDriverWait(driver, 15).until(
        lambda d: d.find_element(By.ID, "totalLines").text != "0"
    )

    copy_btn = driver.find_element(By.ID, "copyButton")
    original_text = copy_btn.text

    copy_btn.click()
    time.sleep(0.5)

    # Check for visual feedback (button text should change temporarily)
    # Note: This may show "Failed to copy" in headless mode due to clipboard restrictions
    WebDriverWait(driver, 5).until(
        lambda d: d.find_element(By.ID, "copyButton").text != original_text
    )

    # Verify the button text changed to some feedback message
    feedback_text = copy_btn.text.upper()
    assert (
        feedback_text in ["COPIED", "FAILED TO COPY"]
        or "COPIED" in feedback_text
        or "FAILED" in feedback_text
    )


@pytest.mark.web
def test_log_container_scrolling(driver):
    """Test that log container has proper scrolling behavior"""
    login_to_logs(driver)

    # Wait for logs to load
    WebDriverWait(driver, 20).until(
        lambda d: d.find_element(By.ID, "loadingMessage").value_of_css_property(
            "display"
        )
        == "none"
    )

    WebDriverWait(driver, 15).until(
        lambda d: d.find_element(By.ID, "totalLines").text != "0"
    )

    log_viewer = driver.find_element(By.ID, "logViewer")

    # Check CSS properties for scrolling
    overflow_y = log_viewer.value_of_css_property("overflow-y")
    height = log_viewer.value_of_css_property("height")

    assert overflow_y == "auto"
    assert height == "600px"  # From the CSS
