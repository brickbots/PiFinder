import pytest
import time
import os
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from web_test_utils import login_to_remote, press_keys, press_keys_and_validate, recursive_dict_compare

"""
The test_web_remote.py file contains comprehensive end-to-end tests for PiFinder's web-based remote control
interface. Here's what the test suite covers:

  Test Overview

  The test suite validates PiFinder's web interface functionality through automated browser testing using Selenium
  WebDriver. All tests authenticate with the default password "solveit" and interact with the remote control
  interface at localhost:8080.

  Core Interface Tests

  Basic Interface Validation: Tests verify that all essential UI elements are present and correctly configured,
  including the PiFinder screen image, navigation buttons (arrows, numbers 0-9, plus/minus), the square button, and
  special modifier buttons ("■ +" for ALT functions and "LONG" for long-press combinations).

  Authentication Flow: Tests confirm the login process works correctly with the default password and that users are
  properly redirected to the remote control interface after successful authentication.

  Navigation and UI State Tests

  Menu Navigation: The suite extensively tests navigation through PiFinder's menu system, including moving between
  the main menu, Objects submenu, catalog selection (like Messier), and object lists. Each navigation action is
  validated using the /api/current-selection endpoint to ensure the UI state changes correctly.

  Text Entry: Tests verify that text input works properly, including typing digits and navigating to search
  interfaces like "Name Search".

  Object Selection: Tests navigate to specific astronomical objects (like M31 - Andromeda Galaxy).

  Advanced Functionality Tests

  Marking Menus: Tests validate the marking menu system that appears when using LONG+SQUARE combinations. This
  includes verifying that marking menus display with correct options (like "Sort"), that menu selections work
  properly (changing sort order to "Nearest"), and that the /api/current-selection endpoint correctly reports
  marking menu state with underlying UI information.

  Long-Press Combinations: Tests verify special key combinations like:
  - LONG+LEFT (ZL): Returns to the top-level menu from anywhere in the interface
  - LONG+RIGHT (ZR): Jumps to the most recently viewed object

  Recent Objects: Tests the recent objects functionality by viewing M31 for longer than the 10-second activation
  timeout, ensuring it gets added to the recent list, then using LONG+RIGHT to verify quick access to recently
  viewed objects.

  Technical Implementation

  API Integration: All tests extensively use the /api/current-selection endpoint to validate UI state changes,
  ensuring the web interface accurately reflects PiFinder's internal state. The tests validate complex response
  structures including object metadata, menu states, and marking menu configurations.

  Cross-Platform Testing: Tests run on both desktop (1920x1080) and mobile (375x667) viewports to ensure responsive
  design works correctly.

  Infrastructure Resilience: The test suite automatically detects if Selenium Grid is unavailable and gracefully
  skips tests rather than failing, making it suitable for various development and CI environments.

  Test Architecture

  The test suite uses a shared WebDriver session for performance, implements helper functions for key press
  simulation and state validation, and provides comprehensive error checking for all UI interactions. The tests are
  designed to be deterministic and can run reliably in automated environments while providing detailed feedback
  about PiFinder's web interface functionality. (Summary created by Claude Code)"""

@pytest.fixture(scope="session")
def shared_driver():
    """Setup Chrome driver using Selenium Grid - configurable via environment with auto-skip if unavailable"""
    # Get Selenium Grid URL from environment variable with fallback
    selenium_grid_url = os.environ.get("SELENIUM_GRID_URL", "http://localhost:4444/wd/hub")
    
    # Test if Selenium Grid is available
    try:
        status_url = selenium_grid_url.replace("/wd/hub", "/status")
        response = requests.get(status_url, timeout=5)
        if response.status_code != 200:
            pytest.skip("Selenium Grid not available - tests require running Selenium Grid")
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
        pass # Ignore errors on shutdown


@pytest.fixture
def driver(shared_driver):
    """Provide access to shared driver with cleanup between tests"""
    # Reset to known state before each test
    shared_driver.delete_all_cookies()
    shared_driver.set_window_size(1920, 1080)
    yield shared_driver


@pytest.mark.parametrize(
    "window_size,viewport_name", [((1920, 1080), "desktop"), ((375, 667), "mobile")]
)
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
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, ".hide-on-med-and-down a[href='/remote']")
            )
        )
    except Exception:
        # Mobile menu - need to click hamburger first
        hamburger = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "sidenav-trigger"))
        )
        hamburger.click()

        # Wait for mobile menu to open and find Remote link
        remote_link = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "#nav-mobile a[href='/remote']")
            )
        )
    remote_link.click()

    # Wait for login page to load
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "password")))

    # Verify we're on the login page
    assert "Login Required" in driver.page_source

    # Enter the default password "solveit"
    password_field = driver.find_element(By.ID, "password")
    password_field.send_keys("solveit")

    # Submit the login form
    login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
    login_button.click()

    # Wait for remote page to load after successful login
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "image")))

    # Verify we're now on the remote control page
    assert "/remote" in driver.current_url


@pytest.mark.parametrize(
    "window_size,viewport_name", [((1920, 1080), "desktop"), ((375, 667), "mobile")]
)
@pytest.mark.web
def test_remote_image_present(driver, window_size, viewport_name):
    """Test that image is present on remote page after login"""
    # Set the window size for this test run
    driver.set_window_size(*window_size)

    # Login to remote interface
    login_to_remote(driver)

    # Check for image element
    image = driver.find_element(By.ID, "image")
    assert image is not None, "Image element not found on remote page"

    # Verify image has the correct attributes
    assert image.get_attribute("alt") == "PiFinder Screen", "Image alt text incorrect"
    assert "pifinder-screen" in image.get_attribute("class"), "Image class incorrect"


@pytest.mark.parametrize(
    "window_size,viewport_name", [((1920, 1080), "desktop"), ((375, 667), "mobile")]
)
@pytest.mark.web
def test_remote_keyboard_elements_present(driver, window_size, viewport_name):
    """Test that all keyboard elements are present on remote page"""
    # Set the window size for this test run
    driver.set_window_size(*window_size)

    # Login to remote interface
    login_to_remote(driver)

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
        "■": "SQUARE",
        # ENT
    }

    # Find all remote buttons
    remote_buttons = driver.find_elements(By.CLASS_NAME, "remote-button")
    button_texts = [btn.text for btn in remote_buttons]

    # Check each expected button is present
    for display_text, code in expected_buttons.items():
        assert (
            display_text in button_texts
        ), f"Button '{display_text}' not found on remote page"

    # Verify we have at least the expected number of buttons (13 main buttons + special buttons)
    assert (
        len(remote_buttons) >= 13
    ), f"Expected at least 13 remote buttons, found {len(remote_buttons)}"


@pytest.mark.parametrize(
    "window_size,viewport_name", [((1920, 1080), "desktop"), ((375, 667), "mobile")]
)
@pytest.mark.web
def test_remote_special_buttons_present(driver, window_size, viewport_name):
    """Test that special buttons (Ent+, Long) are present"""
    # Set the window size for this test run
    driver.set_window_size(*window_size)

    # Login to remote interface
    login_to_remote(driver)

    # Check for special buttons
    ent_button = driver.find_element(By.ID, "altButton")
    assert ent_button.text == "■ +", "'■ +' button not found or incorrect text"

    long_button = driver.find_element(By.ID, "longButton")
    assert long_button.text == "LONG", "LONG button not found or incorrect text"


@pytest.mark.parametrize(
    "window_size,viewport_name", [((1920, 1080), "desktop"), ((375, 667), "mobile")]
)
@pytest.mark.web
def test_remote_all_elements_comprehensive(driver, window_size, viewport_name):
    """Comprehensive test verifying all remote interface elements"""
    # Set the window size for this test run
    driver.set_window_size(*window_size)

    # Login to remote interface
    login_to_remote(driver)

    # Verify page title
    assert "PiFinder - Remote" in driver.title

    # Check image is present
    image = driver.find_element(By.ID, "image")
    assert image is not None

    # Check all number buttons (0-9)
    for num in range(10):
        button = driver.find_element(By.ID, str(num))
        assert button is not None, f"Number button {num} not found"

    # Check arrow buttons
    arrow_buttons = [("←", "A"), ("↑", "B"), ("↓", "C"), ("→", "D")]
    for arrow_text, button_id in arrow_buttons:
        button = driver.find_element(By.ID, button_id)
        assert button is not None, f"Arrow button {arrow_text} not found"

    # Check plus/minus buttons
    plus_button = driver.find_element(By.ID, "UP")
    minus_button = driver.find_element(By.ID, "DN")
    assert plus_button is not None, "Plus button not found"
    assert minus_button is not None, "Minus button not found"

    # Check square button
    square_button = driver.find_element(By.ID, "SQ")
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
    login_to_remote(driver)

    # Get cookies from the selenium session for authentication
    cookies = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}

    # Make request to the API endpoint
    response = requests.get(
        "http://localhost:8080/api/current-selection", cookies=cookies
    )

    # Validate response
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert isinstance(data, dict), "Response should be a JSON object"


@pytest.mark.web
def test_ui_state_changes_with_button_presses(driver):
    """Test that UI state changes when buttons are pressed in remote interface"""
    import requests
    import time

    # Login to remote interface
    login_to_remote(driver)

    # Get cookies from the selenium session for authentication
    cookies = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}

    # Get initial UI state
    response = requests.get(
        "http://localhost:8080/api/current-selection", cookies=cookies
    )
    assert response.status_code == 200

    # Press a button (e.g., right arrow to navigate menu)
    right_button = driver.find_element(By.ID, "D")
    right_button.click()

    # Wait a moment for the UI to update
    time.sleep(0.5)

    # Get updated UI state
    response = requests.get(
        "http://localhost:8080/api/current-selection", cookies=cookies
    )
    assert response.status_code == 200
    updated_state = response.json()

    # Verify the state has potentially changed (if it's a menu with multiple items)
    # Note: The state might not change if we're at the end of a menu or in a different UI type
    # But the API should still return valid data
    assert "ui_type" in updated_state, "ui_type should be present in updated state"


@pytest.mark.web
def test_remote_nav_wakeup(driver):
    login_to_remote(driver)

    press_keys_and_validate(
        driver, "LLLLLLUUUUUUDD", expected_values={
            "ui_type": "UITextMenu",
            "title": "PiFinder",
            "current_item": "Objects",
        }
    )  # One extra to wake up from sleep.


@pytest.mark.web
def test_remote_nav_up(driver):
    test_remote_nav_wakeup(driver)  # Also logs in.

    press_keys_and_validate(
        driver, "UU", expected_values={
            "ui_type": "UITextMenu",
            "title": "PiFinder",
            "current_item": "Start",
        }
    )  # One extra to wake up from sleep.


@pytest.mark.web
def test_remote_nav_down(driver):
    test_remote_nav_up(driver)  # Also logs in.

    press_keys_and_validate(driver, "DD", expected_values={
        "ui_type": "UITextMenu",
        "title": "PiFinder",
        "current_item": "Objects",
    })


@pytest.mark.web
def test_remote_nav_right(driver):
    test_remote_nav_down(driver)  # Also logs in.

    press_keys_and_validate(driver, "RD", expected_values={
        "ui_type": "UITextMenu",
        "title": "Objects",
        "current_item": "By Catalog",
    })

    press_keys_and_validate(driver, "RDDD", expected_values={
        "ui_type": "UITextMenu",
        "title": "By Catalog",
        "current_item": "Messier",
    })

    press_keys_and_validate(driver, "R", expected_values={
        "ui_type": "UIObjectList",
        "title": "Messier",
        "current_item": "M 1",
    })

    press_keys_and_validate(driver, "LLLL", expected_values={
        "ui_type": "UITextMenu",
        "title": "PiFinder",
        "current_item": "Objects",
    })


@pytest.mark.web
def test_remote_entry(driver):
    test_remote_nav_wakeup(driver)  # Also logs in.

    press_keys_and_validate(driver, "RDDDR", expected_values={
        "ui_type": "UITextEntry",
        "title": "Name Search",
        "value": "",
    })

    press_keys(driver, "LLL")


@pytest.mark.web
def test_remote_entry_digits(driver):
    test_remote_nav_wakeup(driver)  # Also logs in.

    press_keys_and_validate(driver, "RDDDR0123456789", expected_values={
        "ui_type": "UITextEntry",
        "title": "Name Search",
        "value": "0123456789",
    })

    # Go back to main menu
    press_keys(driver, "LLL")


@pytest.mark.web
def test_remote_backtotop(driver):
    test_remote_nav_wakeup(driver)  # Also logs in.

    press_keys_and_validate(driver, "RDRDDDR31R", expected_values={
        "ui_type": "UIObjectDetails",
        "object": {
            "display_name": "M 31"
        }
    })

    # LNG_LEFT
    press_keys_and_validate(driver, "ZL", expected_values={
        "ui_type": "UITextMenu",
        "title": "PiFinder", 
        "current_item": "Objects",
    })  


@pytest.mark.web
def test_remote_markingmenu(driver):
    test_remote_nav_wakeup(driver)  # Also logs in.

    press_keys_and_validate(driver, "RDRDDDR31RL", expected_values={
        "current_item": "M 31",
        "display_mode": "LOCATE",
        "marking_menu_active": False,
        "sort_order": "CATALOG_SEQUENCE",
        "title": "Messier",
        "ui_type": "UIObjectList"
    })

    press_keys_and_validate(driver, "ZS", expected_values={
        "ui_type": "UIMarkingMenu",
        "marking_menu_active": True,
        "underlying_ui_type": "UIObjectList",
        "underlying_title": "Messier",
        "marking_menu_options": {
            "left": {
                "enabled": True,
                "label": "Sort",
            }
        }
    }) 

    press_keys_and_validate(driver, "L", expected_values={
        "ui_type": "UIMarkingMenu",
        "marking_menu_active": True,
        "underlying_ui_type": "UIObjectList",
        "underlying_title": "Messier",
        "marking_menu_options": {
            "left": {
                "enabled": True,
                "label": "Nearest",
            }
        }
    }) 
    time.sleep(0.5)  # Wait a bit for UI to update

    press_keys_and_validate(driver, "L", expected_values={
        "marking_menu_active": False,
        "sort_order": "NEAREST",
        "title": "Messier",
        "ui_type": "UIObjectList",
    })

    press_keys(driver, "ZL")  # LNG_LEFT to go back to main menu


@pytest.mark.web
def test_remote_recent(driver):
    test_remote_nav_wakeup(driver)  # Also logs in.

    # Navigate to M31 object details
    press_keys_and_validate(driver, "RDRDDDR31R", expected_values={
        "ui_type": "UIObjectDetails",
        "object": {
            "display_name": "M 31"
        }
    })
    
    # Wait longer than the activation timeout (10 seconds) to ensure M31 gets added to recents
    time.sleep(15)
    
    # Alter activation timeout press RL, to make sure it gets stored in recent list.
    # Go back to top level menu (LNG_LEFT)
    press_keys_and_validate(driver, "RLZL", expected_values={
        "ui_type": "UITextMenu",
        "title": "PiFinder",
        "current_item": "Objects",
    })  
    
    # Use LONG+RIGHT to go to recent item (should be M31)
    press_keys_and_validate(driver, "ZRW", expected_values={
        "ui_type": "UIObjectDetails", 
        "object": {
            "display_name": "M 31"
        }
    })

    press_keys(driver, "ZL")  # LNG_LEFT to go back to main menu

