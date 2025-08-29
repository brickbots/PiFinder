import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


@pytest.fixture
def driver():
    """Setup Chrome driver using Selenium Grid on localhost:4444"""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    driver = webdriver.Remote(
        command_executor="http://192.168.178.94:4444/wd/hub",
        options=chrome_options
    )
    yield driver
    driver.quit()


@pytest.mark.web
def test_webpage_loads_and_displays_image(driver):
    """Test that the PiFinder web interface loads and displays an image"""
    # Navigate to localhost:8080
    driver.get("http://localhost:8080")
    
    # Wait for the page to load and check title
    WebDriverWait(driver, 10).until(
        lambda d: d.title != ""
    )
    
    # Verify page loaded successfully
    assert "PiFinder - Home" in driver.title
    
    # Look for image elements in the page
    # Common selectors for images
    images = driver.find_elements(By.TAG_NAME, "img")
    canvas_elements = driver.find_elements(By.TAG_NAME, "canvas")
    video_elements = driver.find_elements(By.TAG_NAME, "video")
    
    # Assert that at least one visual element is present
    visual_elements_count = len(images) + len(canvas_elements) + len(video_elements)
    assert visual_elements_count > 0, "No images, canvas, or video elements found on the page"
    
    # If there are img elements, verify at least one has a src attribute
    if images:
        img_with_src = [img for img in images if img.get_attribute("src")]
        assert len(img_with_src) > 0, "Found img elements but none have src attribute"
    
    # Verify page content is loaded (not empty body)
    body = driver.find_element(By.TAG_NAME, "body")
    assert body.text.strip() != "", "Page body appears to be empty"
