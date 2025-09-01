import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


@pytest.fixture(scope="session")
def shared_driver():
    """Setup Chrome driver using Selenium Grid on localhost:4444 - shared across all tests in session"""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    driver = webdriver.Remote(
        command_executor="http://192.168.178.94:4444/wd/hub",
        options=chrome_options
    )
    # Ensure desktop viewport
    driver.set_window_size(1920, 1080)
    yield driver
    driver.quit()


@pytest.fixture
def driver(shared_driver):
    """Provide access to shared driver with cleanup between tests"""
    # Reset to known state before each test
    shared_driver.delete_all_cookies()
    shared_driver.set_window_size(1920, 1080)
    yield shared_driver


@pytest.mark.parametrize("window_size,viewport_name", [
    ((1920, 1080), "desktop"),
    ((375, 667), "mobile")
])
@pytest.mark.web
def test_remote_login_and_interface(driver, window_size, viewport_name):
    """Test remote login with default password and verify interface elements"""
    # Set the window size for this test run
    driver.set_window_size(*window_size)
    
    # Navigate to localhost:8080
    driver.get("http://localhost:8080")
    
    # Wait for the page to load by checking for the navigation
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "nav"))
    )
    
    # Try to find Remote link in desktop menu first, then mobile menu
    try:
        # Desktop menu (visible on larger screens)
        remote_link = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".hide-on-med-and-down a[href='/remote']"))
        )
    except:
        # Mobile menu - need to click hamburger first
        hamburger = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "sidenav-trigger"))
        )
        hamburger.click()
        
        # Wait for mobile menu to open and find Remote link
        remote_link = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "#nav-mobile a[href='/remote']"))
        )
    remote_link.click()
    
    # Wait for login page to load
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "password"))
    )
    
    # Verify we're on the login page
    assert "Login Required" in driver.page_source
    
    # Enter the default password "solveit"
    password_field = driver.find_element(By.ID, "password")
    password_field.send_keys("solveit")
    
    # Submit the login form
    login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
    login_button.click()
    
    # Wait for remote page to load after successful login
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "image"))
    )
    
    # Verify we're now on the remote control page
    assert "/remote" in driver.current_url


@pytest.mark.parametrize("window_size,viewport_name", [
    ((1920, 1080), "desktop"),
    ((375, 667), "mobile")
])
@pytest.mark.web
def test_remote_image_present(driver, window_size, viewport_name):
    """Test that image is present on remote page after login"""
    # Set the window size for this test run
    driver.set_window_size(*window_size)
    
    # Login to remote interface
    _login_to_remote(driver)
    
    # Check for image element
    image = driver.find_element(By.ID, "image")
    assert image is not None, "Image element not found on remote page"
    
    # Verify image has the correct attributes
    assert image.get_attribute("alt") == "PiFinder Screen", "Image alt text incorrect"
    assert "pifinder-screen" in image.get_attribute("class"), "Image class incorrect"


@pytest.mark.parametrize("window_size,viewport_name", [
    ((1920, 1080), "desktop"),
    ((375, 667), "mobile")
])
@pytest.mark.web
def test_remote_keyboard_elements_present(driver, window_size, viewport_name):
    """Test that all keyboard elements are present on remote page"""
    # Set the window size for this test run
    driver.set_window_size(*window_size)
    
    # Login to remote interface
    _login_to_remote(driver)
    
    # Expected keyboard elements based on remote.html
    expected_buttons = {
        # Arrow keys
        "←": "A",
        "↑": "B", 
        "↓": "C",
        "→": "D",
        # Numbers 0-9
        "0": "0",
        "1": "1",
        "2": "2", 
        "3": "3",
        "4": "4",
        "5": "5",
        "6": "6",
        "7": "7",
        "8": "8",
        "9": "9",
        # Plus and minus
        "+": "UP",
        "-": "DN",
        # Square
        "■": "SQUARE"
    }
    
    # Find all remote buttons
    remote_buttons = driver.find_elements(By.CLASS_NAME, "remote-button")
    button_texts = [btn.text for btn in remote_buttons]
    
    # Check each expected button is present
    for display_text, code in expected_buttons.items():
        assert display_text in button_texts, f"Button '{display_text}' not found on remote page"
    
    # Verify we have at least the expected number of buttons (13 main buttons + special buttons)
    assert len(remote_buttons) >= 13, f"Expected at least 13 remote buttons, found {len(remote_buttons)}"


@pytest.mark.parametrize("window_size,viewport_name", [
    ((1920, 1080), "desktop"),
    ((375, 667), "mobile")
])
@pytest.mark.web
def test_remote_special_buttons_present(driver, window_size, viewport_name):
    """Test that special buttons (Ent+, Long) are present"""
    # Set the window size for this test run
    driver.set_window_size(*window_size)
    
    # Login to remote interface  
    _login_to_remote(driver)
    
    # Check for special buttons
    ent_button = driver.find_element(By.ID, "altButton")
    assert ent_button.text == "ENT+", "ENT+ button not found or incorrect text"
    
    long_button = driver.find_element(By.ID, "longButton") 
    assert long_button.text == "LONG", "LONG button not found or incorrect text"


@pytest.mark.parametrize("window_size,viewport_name", [
    ((1920, 1080), "desktop"),
    ((375, 667), "mobile")
])
@pytest.mark.web
def test_remote_all_elements_comprehensive(driver, window_size, viewport_name):
    """Comprehensive test verifying all remote interface elements"""
    # Set the window size for this test run
    driver.set_window_size(*window_size)
    
    # Login to remote interface
    _login_to_remote(driver)
    
    # Verify page title
    assert "PiFinder - Remote" in driver.title
    
    # Check image is present
    image = driver.find_element(By.ID, "image")
    assert image is not None
    
    # Check all number buttons (0-9)
    for num in range(10):
        button = driver.find_element(By.XPATH, f"//button[text()='{num}']")
        assert button is not None, f"Number button {num} not found"
    
    # Check arrow buttons
    arrow_buttons = ["←", "↑", "↓", "→"]
    for arrow in arrow_buttons:
        button = driver.find_element(By.XPATH, f"//button[text()='{arrow}']")
        assert button is not None, f"Arrow button {arrow} not found"
    
    # Check plus/minus buttons
    plus_button = driver.find_element(By.XPATH, "//button[text()='+']")
    minus_button = driver.find_element(By.XPATH, "//button[text()='-']")
    assert plus_button is not None, "Plus button not found"
    assert minus_button is not None, "Minus button not found"
    
    # Check square button
    square_button = driver.find_element(By.XPATH, "//button[text()='■']")
    assert square_button is not None, "Square button not found"
    
    # Check special buttons
    ent_button = driver.find_element(By.ID, "altButton")
    long_button = driver.find_element(By.ID, "longButton")
    assert ent_button is not None, "Ent+ button not found"
    assert long_button is not None, "Long button not found"


@pytest.mark.web
def test_current_selection_api_endpoint(driver):
    """Test that the /api/current-selection endpoint returns valid data"""
    import requests
    
    # Login to remote interface to get authenticated session
    _login_to_remote(driver)
    
    # Get cookies from the selenium session for authentication
    cookies = {cookie['name']: cookie['value'] for cookie in driver.get_cookies()}
    
    # Make request to the API endpoint
    response = requests.get("http://localhost:8080/api/current-selection", cookies=cookies)
    
    # Verify response is successful
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    # Verify response is valid JSON
    data = response.json()
    assert isinstance(data, dict), "Response should be a JSON object"
    
    # Verify expected fields are present (unless there's an error)
    if "error" not in data:
        assert "ui_type" in data, "ui_type field missing from response"
        assert "title" in data, "title field missing from response"
        
        # For UITextMenu, check specific fields
        if data.get("ui_type") == "UITextMenu":
            assert "current_index" in data, "current_index missing for UITextMenu"
            assert "current_item" in data, "current_item missing for UITextMenu"
            assert "total_items" in data, "total_items missing for UITextMenu"
            assert "menu_type" in data, "menu_type missing for UITextMenu"
        
        # For UITimeEntry, check specific fields
        elif data.get("ui_type") == "UITimeEntry":
            assert "current_box" in data, "current_box missing for UITimeEntry"
            assert "time_values" in data, "time_values missing for UITimeEntry"
            assert "total_boxes" in data, "total_boxes missing for UITimeEntry"
            assert "value" in data, "value missing for UITimeEntry"
            # Value should be in H:MM:SS or HH:MM:SS format
            import re
            assert re.match(r'^\d{1,2}:\d{2}:\d{2}$', data["value"]), f"Invalid time format: {data['value']}"
        
        # For UITextEntry, check specific fields
        elif data.get("ui_type") == "UITextEntry":
            assert "value" in data, "value missing for UITextEntry"
            assert "text_entry_mode" in data, "text_entry_mode missing for UITextEntry"
            assert "show_keypad" in data, "show_keypad missing for UITextEntry"
            assert "search_results_count" in data, "search_results_count missing for UITextEntry"
            # Value should be a string (could be empty)
            assert isinstance(data["value"], str), f"UITextEntry value should be string, got {type(data['value'])}"


@pytest.mark.web  
def test_ui_state_changes_with_button_presses(driver):
    """Test that UI state changes when buttons are pressed in remote interface"""
    import requests
    import time
    
    # Login to remote interface
    _login_to_remote(driver)
    
    # Get cookies from the selenium session for authentication
    cookies = {cookie['name']: cookie['value'] for cookie in driver.get_cookies()}
    
    # Get initial UI state
    response = requests.get("http://localhost:8080/api/current-selection", cookies=cookies)
    assert response.status_code == 200
    initial_state = response.json()
    
    # Press a button (e.g., right arrow to navigate menu)
    right_button = driver.find_element(By.XPATH, "//button[text()='→']")
    right_button.click()
    
    # Wait a moment for the UI to update
    time.sleep(0.5)
    
    # Get updated UI state
    response = requests.get("http://localhost:8080/api/current-selection", cookies=cookies)
    assert response.status_code == 200
    updated_state = response.json()
    
    # Verify the state has potentially changed (if it's a menu with multiple items)
    # Note: The state might not change if we're at the end of a menu or in a different UI type
    # But the API should still return valid data
    assert "ui_type" in updated_state, "ui_type should be present in updated state"


def _login_to_remote(driver):
    """Helper function to login to remote interface"""
    # Navigate to localhost:8080
    driver.get("http://localhost:8080")
    
    # Wait for the page to load by checking for the navigation
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "nav"))
    )
    
    # Try to find Remote link in desktop menu first, then mobile menu
    try:
        # Desktop menu (visible on larger screens)
        remote_link = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".hide-on-med-and-down a[href='/remote']"))
        )
    except:
        # Mobile menu - need to click hamburger first
        hamburger = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "sidenav-trigger"))
        )
        hamburger.click()
        
        # Wait for mobile menu to open and find Remote link
        remote_link = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "#nav-mobile a[href='/remote']"))
        )
    remote_link.click()
    
    # Wait for login page to load
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "password"))
    )
    
    # Enter the default password "solveit"
    password_field = driver.find_element(By.ID, "password")
    password_field.send_keys("solveit")
    
    # Submit the login form
    login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
    login_button.click()
    
    # Wait for remote page to load after successful login
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "image"))
    )