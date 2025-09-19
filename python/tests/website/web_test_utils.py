"""
Shared utilities for web interface testing
"""

import os
import time
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def get_homepage_url():
    """
    Helper function to get the homepage URL from environment variable or default
    """
    return os.environ.get("PIFINDER_HOMEPAGE", "http://localhost:8080")


def login_to_remote(driver):
    """Helper function to login to remote interface"""
    navigate_to_page(driver, "/remote")
    login_with_password(driver)
    # Wait for remote page to load after successful login
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "image")))


def login_to_logs(driver):
    """Helper function to login and navigate to logs page"""
    navigate_to_page(driver, "/logs")


def login_to_tools(driver):
    """Helper function to login and navigate to tools page"""
    navigate_to_page(driver, "/tools")


def login_to_locations(driver):
    """Helper function to login and navigate to locations page"""
    navigate_to_page(driver, "/locations")


def login_to_equipment(driver):
    """Helper function to login and navigate to equipment page"""
    navigate_to_page(driver, "/equipment")


def login_to_network(driver):
    """Helper function to login and navigate to network page"""
    navigate_to_page(driver, "/network")


def login_to_observations(driver):
    """Helper function to login and navigate to observations page"""
    navigate_to_page(driver, "/observations")


def press_keys(driver, keys):
    """
    Helper function to press keys on remote UI
    """
    # Press each key in sequence
    for key_char in keys:
        # Map key characters to button IDs
        key_mapping = {
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
            "L": "LEFT",
            "R": "RIGHT",
            "U": "UP",
            "D": "DOWN",
            "←": "LEFT",
            "→": "RIGHT",
            "↑": "UP",
            "↓": "DOWN",
            "+": "PLUS",
            "-": "MINUS",
            "S": "SQUARE",
            "■": "SQUARE",
            "T": "altButton",
            "Z": "longButton",
            "W": "extra WAIT",
        }

        if key_char in key_mapping:
            if key_char == "W":
                time.sleep(1)
                continue

            button = driver.find_element(By.ID, key_mapping[key_char])
            button.click()
            time.sleep(0.2)

            # Extra delay after special button presses
            if key_char in ["T", "Z"]:
                WebDriverWait(driver, 1).until(
                    lambda d: "pressed" in button.get_attribute("class")
                )

        time.sleep(0.5)


def press_keys_and_validate(driver, keys, expected_values):
    """
    Helper function to press keys on remote UI and validate response
    """
    # Get cookies from the selenium session for authentication
    cookies = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}

    # Press the keys
    press_keys(driver, keys)

    # Get the API response after pressing keys
    response = requests.get(
        f"{get_homepage_url()}/api/current-selection", cookies=cookies
    )

    # Validate basic response structure
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    data = response.json()
    assert isinstance(data, dict), "Response should be a JSON object"

    # Recursively compare expected values with actual response
    recursive_dict_compare(data, expected_values)


def navigate_to_page(driver, page_path):
    """
    Generic helper function to navigate to any page on the web interface
    Handles both desktop and mobile navigation patterns
    Uses PIFINDER_HOMEPAGE environment variable or defaults to localhost:8080
    """
    driver.get(get_homepage_url())

    # Wait for the page to load by checking for the navigation
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "nav"))
    )

    # Try to find link in desktop menu first, then mobile menu
    try:
        # Desktop menu (visible on larger screens)
        page_link = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, f".hide-on-med-and-down a[href='{page_path}']")
            )
        )
    except Exception:
        # Mobile menu - need to click hamburger first
        hamburger = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "sidenav-trigger"))
        )
        hamburger.click()

        # Wait for mobile menu to open and find page link
        page_link = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, f"#nav-mobile a[href='{page_path}']")
            )
        )
    page_link.click()


def login_with_password(driver, password="solveit"):
    """
    Helper function to handle password authentication
    """
    # Wait for login page to load
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "password")))

    # Enter the password
    password_field = driver.find_element(By.ID, "password")
    password_field.send_keys(password)

    # Submit the login form
    login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
    login_button.click()


def recursive_dict_compare(actual, expected):
    """
    Recursively compare expected dict values with actual response data
    """
    for key, expected_value in expected.items():
        assert (
            key in actual
        ), f"Expected key '{key}' not found in response. Available keys: {list(actual.keys())}"

        actual_value = actual[key]

        if isinstance(expected_value, dict):
            assert isinstance(
                actual_value, dict
            ), f"Expected '{key}' to be a dict, but got {type(actual_value)}"
            recursive_dict_compare(actual_value, expected_value)
        elif isinstance(expected_value, list):
            assert isinstance(
                actual_value, list
            ), f"Expected '{key}' to be a list, but got {type(actual_value)}"
            assert (
                len(actual_value) == len(expected_value)
            ), f"Expected '{key}' list length {len(expected_value)}, got {len(actual_value)}"
            for i, (actual_item, expected_item) in enumerate(
                zip(actual_value, expected_value)
            ):
                if isinstance(expected_item, dict):
                    recursive_dict_compare(actual_item, expected_item)
                else:
                    assert (
                        actual_item == expected_item
                    ), f"Expected '{key}[{i}]' to be {expected_item}, got {actual_item}"
        else:
            assert (
                actual_value == expected_value
            ), f"Expected '{key}' to be {expected_value}, got {actual_value}"
