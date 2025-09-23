import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from web_test_utils import get_homepage_url


@pytest.mark.web
def test_webpage_loads_and_displays_image(driver):
    """Test that the PiFinder web interface loads and displays an image"""
    # Navigate to localhost:8080
    driver.get(get_homepage_url())

    # Wait for the page to load and check title
    WebDriverWait(driver, 10).until(lambda d: d.title != "")

    # Verify page loaded successfully
    assert "PiFinder - Home" in driver.title

    # Look for image elements in the page
    # Common selectors for images
    images = driver.find_elements(By.TAG_NAME, "img")
    canvas_elements = driver.find_elements(By.TAG_NAME, "canvas")
    video_elements = driver.find_elements(By.TAG_NAME, "video")

    # Assert that at least one visual element is present
    visual_elements_count = len(images) + len(canvas_elements) + len(video_elements)
    assert (
        visual_elements_count > 0
    ), "No images, canvas, or video elements found on the page"

    # If there are img elements, verify at least one has a src attribute
    if images:
        img_with_src = [img for img in images if img.get_attribute("src")]
        assert len(img_with_src) > 0, "Found img elements but none have src attribute"

    # Verify page content is loaded (not empty body)
    body = driver.find_element(By.TAG_NAME, "body")
    assert body.text.strip() != "", "Page body appears to be empty"


@pytest.mark.web
def test_mode_element_present(driver):
    """Test that Mode information is displayed on the page"""
    driver.get(get_homepage_url())

    # Wait for page to load
    WebDriverWait(driver, 10).until(lambda d: d.title != "")

    # Look for Mode text - it should be present in the table
    body_text = driver.find_element(By.TAG_NAME, "body").text
    assert "Mode" in body_text, "Mode information not found on the page"


@pytest.mark.web
def test_lat_lon_elements_present(driver):
    """Test that Latitude and Longitude information is displayed on the page"""
    driver.get(get_homepage_url())

    # Wait for page to load
    WebDriverWait(driver, 10).until(lambda d: d.title != "")

    # Look for lat/lon text
    body_text = driver.find_element(By.TAG_NAME, "body").text
    assert "lat" in body_text.lower(), "Latitude information not found on the page"
    assert "lon" in body_text.lower(), "Longitude information not found on the page"


@pytest.mark.web
def test_sky_position_element_present(driver):
    """Test that Sky Position information is displayed on the page"""
    driver.get(get_homepage_url())

    # Wait for page to load
    WebDriverWait(driver, 10).until(lambda d: d.title != "")

    # Look for Sky Position text
    body_text = driver.find_element(By.TAG_NAME, "body").text
    assert "Sky Position" in body_text, "Sky Position information not found on the page"

    # Also check for RA and DEC labels
    assert "RA:" in body_text, "RA coordinate not found on the page"
    assert "DEC:" in body_text, "DEC coordinate not found on the page"


@pytest.mark.web
def test_software_version_element_present(driver):
    """Test that Software Version information is displayed on the page"""
    driver.get(get_homepage_url())

    # Wait for page to load
    WebDriverWait(driver, 10).until(lambda d: d.title != "")

    # Look for Software Version text
    body_text = driver.find_element(By.TAG_NAME, "body").text
    assert (
        "Software Version" in body_text
    ), "Software Version information not found on the page"


@pytest.mark.web
def test_all_main_elements_present(driver):
    """Test that all main UI elements are present in the status table"""
    driver.get(get_homepage_url())

    # Wait for page to load
    WebDriverWait(driver, 10).until(lambda d: d.title != "")

    # Find the main status table
    table = driver.find_element(By.CSS_SELECTOR, "table.grey.darken-2")
    table_text = table.text

    # Check all expected elements are present
    expected_elements = ["Mode", "lat", "lon", "Sky Position", "Software Version"]

    for element in expected_elements:
        assert element in table_text, f"Element '{element}' not found in status table"

    # Verify the table has the expected number of rows (4 main sections)
    rows = table.find_elements(By.TAG_NAME, "tr")
    assert (
        len(rows) >= 4
    ), f"Expected at least 4 rows in status table, found {len(rows)}"
