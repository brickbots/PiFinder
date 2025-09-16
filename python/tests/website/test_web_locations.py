import pytest
import time
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from web_test_utils import (
    login_to_remote,
    press_keys,
    press_keys_and_validate,
    login_to_locations,
    login_with_password,
    get_homepage_url,
)


@pytest.mark.web
def test_locations_page_load(driver):
    """Test that the locations page loads successfully using navigation menu"""
    # Navigate to home page
    driver.get(get_homepage_url())

    # Wait for the page to load by checking for the navigation
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "nav"))
    )

    # Try to find Locations link in desktop menu first, then mobile menu
    try:
        # Desktop menu (visible on larger screens)
        locations_link = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, ".hide-on-med-and-down a[href='/locations']")
            )
        )
    except Exception:
        # Mobile menu - need to click hamburger first
        hamburger = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "sidenav-trigger"))
        )
        hamburger.click()

        # Wait for mobile menu to open and find Locations link
        locations_link = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "#nav-mobile a[href='/locations']")
            )
        )
    locations_link.click()

    # Check if we need to login (redirected to login page)
    try:
        # Wait briefly to see if login form appears
        WebDriverWait(driver, 2).until(
            EC.presence_of_element_located((By.ID, "password"))
        )

        # We're on the login page, enter the default password "solveit"
        password_field = driver.find_element(By.ID, "password")
        password_field.send_keys("solveit")

        # Submit the login form
        login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        login_button.click()

        # Wait for redirect back to locations page after successful login
        WebDriverWait(driver, 10).until(lambda d: "/locations" in d.current_url)
    except Exception:
        # No login required, already authenticated or directly accessible
        pass

    # Wait for locations page to load
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "h5")))

    # Verify we're on the locations page
    assert "/locations" in driver.current_url
    assert "Location Management" in driver.page_source


@pytest.mark.web
def test_locations_table_present(driver):
    """Test that the locations table is present and has expected structure"""
    # Login and load locations page
    _login_to_interface(driver)
    driver.get(f"{get_homepage_url()}/locations")

    # Wait for table to load
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "table"))
    )

    # Verify table structure
    table = driver.find_element(By.TAG_NAME, "table")
    assert table is not None, "Locations table not found"

    # Check for expected table headers
    headers = table.find_elements(By.TAG_NAME, "th")
    header_texts = [header.text for header in headers]

    expected_headers = [
        "Name",
        "Latitude",
        "Longitude",
        "Altitude",
        "Error",
        "Source",
        "Actions",
    ]
    for expected_header in expected_headers:
        assert any(
            expected_header in header for header in header_texts
        ), f"Missing header: {expected_header}"

    # Verify table body exists
    table_body = driver.find_element(By.TAG_NAME, "tbody")
    assert table_body is not None, "Table body not found"


@pytest.mark.web
def test_locations_testloc_present(driver):
    """Test that checks if test locations are present in the table"""
    # Login and navigate to locations page
    _login_to_interface(driver)
    driver.get(f"{get_homepage_url()}/locations")

    # Wait for table to load
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "table"))
    )

    # Check if "Test location" exists in the table
    table_body = driver.find_element(By.TAG_NAME, "tbody")
    existing_locations = table_body.find_elements(By.TAG_NAME, "tr")

    has_test_location = False
    for row in existing_locations:
        cells = row.find_elements(By.TAG_NAME, "td")
        if cells and "test location" in cells[0].text.lower():
            has_test_location = True
            break

    assert has_test_location, "No test locations found in the Location Management table"

    # This test documents the current state - it may pass or fail depending on existing data
    # We don't assert here, just log the result for visibility
    # Test locations present: {has_test_location}


@pytest.mark.web
def test_locations_add_test_locations(driver):
    """Test adding new test locations if they don't already exist"""
    # Login and navigate to locations page
    _login_to_interface(driver)
    driver.get(f"{get_homepage_url()}/locations")

    # Wait for table to load
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "table"))
    )

    # Check which specific test locations exist in the table
    table_body = driver.find_element(By.TAG_NAME, "tbody")
    existing_locations = table_body.find_elements(By.TAG_NAME, "tr")

    existing_location_names = []
    for row in existing_locations:
        cells = row.find_elements(By.TAG_NAME, "td")
        if cells:
            existing_location_names.append(cells[0].text.strip().lower())

    # Define all possible test locations
    all_test_locations = [
        {
            "name": "Test location 1",
            "latitude": "37.7749",
            "longitude": "-122.4194",
            "altitude": "52",
            "error": "10",
        },
        {
            "name": "Test location 2",
            "latitude": "40.7128",
            "longitude": "-74.0060",
            "altitude": "10",
            "error": "15",
        },
        {
            "name": "Test location 3",
            "latitude": "51.5074",
            "longitude": "-0.1278",
            "altitude": "35",
            "error": "8",
        },
    ]

    # Define expected test locations with their values
    expected_test_locations = {
        "test location 1": {
            "latitude": "37.774900",
            "longitude": "-122.419400",
            "altitude": "52.0m",
            "error": "10.0m",
        },
        "test location 2": {
            "latitude": "40.712800",
            "longitude": "-74.006000",
            "altitude": "10.0m",
            "error": "15.0m",
        },
        "test location 3": {
            "latitude": "51.507400",
            "longitude": "-0.127800",
            "altitude": "35.0m",
            "error": "8.0m",
        },
    }

    # Only create test locations that are missing
    for location in all_test_locations:
        location_name_lower = location["name"].lower()
        if location_name_lower not in existing_location_names:
            _add_new_location(driver, location)
            time.sleep(1)  # Small delay between additions

    # Verify all test locations have been created with correct values
    driver.refresh()
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "table"))
    )

    table_body = driver.find_element(By.TAG_NAME, "tbody")
    existing_locations = table_body.find_elements(By.TAG_NAME, "tr")

    # Collect all location data after refresh
    found_locations = {}
    for row in existing_locations:
        cells = row.find_elements(By.TAG_NAME, "td")
        if cells and len(cells) >= 5:  # Name, Lat, Lon, Alt, Error columns
            name = cells[0].text.strip().lower()
            if "test location" in name:
                found_locations[name] = {
                    "latitude": cells[1].text.strip(),
                    "longitude": cells[2].text.strip(),
                    "altitude": cells[3].text.strip(),
                    "error": cells[4].text.strip(),
                }

    # Check that all three test locations are present with correct values
    missing_locations = []
    incorrect_values = []

    for expected_name, expected_values in expected_test_locations.items():
        if expected_name not in found_locations:
            missing_locations.append(expected_name)
        else:
            found_values = found_locations[expected_name]
            for field, expected_value in expected_values.items():
                found_value = found_values[field]
                # For numeric comparisons, extract the numeric part
                if field in ["latitude", "longitude"]:
                    # Compare as floats with tolerance
                    try:
                        expected_float = float(expected_value)
                        found_float = float(found_value)
                        if (
                            abs(expected_float - found_float) > 0.000001
                        ):  # Small tolerance for float precision
                            incorrect_values.append(
                                f"{expected_name} {field}: expected {expected_value}, found {found_value}"
                            )
                    except ValueError:
                        incorrect_values.append(
                            f"{expected_name} {field}: expected {expected_value}, found {found_value}"
                        )
                elif field in ["altitude", "error"]:
                    # These have 'm' suffix, so compare the values directly
                    if found_value != expected_value:
                        incorrect_values.append(
                            f"{expected_name} {field}: expected {expected_value}, found {found_value}"
                        )

    # Assert results
    assert not missing_locations, f"Missing test locations: {missing_locations}"
    assert not incorrect_values, f"Incorrect values found: {incorrect_values}"


@pytest.mark.web
def test_locations_add_dms_location(driver):
    """Test adding a location using DMS (Degrees, Minutes, Seconds) format"""
    # Login and navigate to locations page
    _login_to_interface(driver)
    driver.get(f"{get_homepage_url()}/locations")

    # Wait for table to load
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "table"))
    )

    # Check if "Test location 4" already exists
    table_body = driver.find_element(By.TAG_NAME, "tbody")
    existing_locations = table_body.find_elements(By.TAG_NAME, "tr")

    location_exists = False
    for row in existing_locations:
        cells = row.find_elements(By.TAG_NAME, "td")
        if cells and "test location 4" in cells[0].text.lower():
            location_exists = True
            break

    # Only create if it doesn't exist
    if not location_exists:
        # Click "Add New Location" button
        add_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "a[href='/locations?add_new=1']")
            )
        )
        add_button.click()

        # Wait for form to appear
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "location_form"))
        )

        # Fill in the name field
        name_field = driver.find_element(By.ID, "name-location_form")
        name_field.clear()
        name_field.send_keys("Test location 4")

        # Click the DMS format checkbox using JavaScript to avoid interception
        dms_checkbox = driver.find_element(By.ID, "formatSwitch-location_form")
        driver.execute_script("arguments[0].click();", dms_checkbox)

        # Wait for DMS fields to appear
        WebDriverWait(driver, 5).until(
            EC.visibility_of_element_located((By.ID, "dmsFormat-location_form"))
        )

        # Fill in DMS coordinates for Tokyo: 35°41'22"N 139°41'30"E
        # Latitude: 35 degrees, 41 minutes, 22 seconds
        lat_degrees = driver.find_element(By.ID, "latitudeD-location_form")
        lat_degrees.send_keys("35")

        lat_minutes = driver.find_element(By.ID, "latitudeM-location_form")
        lat_minutes.send_keys("41")

        lat_seconds = driver.find_element(By.ID, "latitudeS-location_form")
        lat_seconds.send_keys("22")

        # Longitude: 139 degrees, 41 minutes, 30 seconds
        lon_degrees = driver.find_element(By.ID, "longitudeD-location_form")
        lon_degrees.send_keys("139")

        lon_minutes = driver.find_element(By.ID, "longitudeM-location_form")
        lon_minutes.send_keys("41")

        lon_seconds = driver.find_element(By.ID, "longitudeS-location_form")
        lon_seconds.send_keys("30")

        # Fill in altitude and error
        altitude_field = driver.find_element(By.ID, "altitude-location_form")
        altitude_field.send_keys("40")

        error_field = driver.find_element(By.ID, "error_in_m-location_form")
        error_field.clear()
        error_field.send_keys("12")

        # Wait for validation to complete
        time.sleep(1.0)

        # Submit the form
        save_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "saveButton-location_form"))
        )

        # Check if save button is enabled
        if save_button.get_attribute("disabled"):
            raise AssertionError("Save button is disabled - form validation failed")

        # Submit the form
        form = driver.find_element(By.ID, "location_form")
        driver.execute_script("arguments[0].submit();", form)
        time.sleep(2.0)

        # Navigate back to locations page
        driver.get(f"{get_homepage_url()}/locations")

    # Verify the location was created with correct values
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "table"))
    )

    table_body = driver.find_element(By.TAG_NAME, "tbody")
    existing_locations = table_body.find_elements(By.TAG_NAME, "tr")

    found_test_location_4 = None
    for row in existing_locations:
        cells = row.find_elements(By.TAG_NAME, "td")
        if cells and "test location 4" in cells[0].text.lower():
            found_test_location_4 = {
                "name": cells[0].text.strip(),
                "latitude": cells[1].text.strip(),
                "longitude": cells[2].text.strip(),
                "altitude": cells[3].text.strip(),
                "error": cells[4].text.strip(),
            }
            break

    # Verify the location exists
    assert (
        found_test_location_4 is not None
    ), "Test location 4 was not found in the table"

    # Verify coordinates are approximately correct (DMS 35°41'22"N 139°41'30"E should convert to ~35.689444, 139.691667)
    expected_lat = 35.689444  # 35 + 41/60 + 22/3600
    expected_lon = 139.691667  # 139 + 41/60 + 30/3600

    actual_lat = float(found_test_location_4["latitude"])
    actual_lon = float(found_test_location_4["longitude"])

    # Allow small tolerance for DMS conversion
    assert (
        abs(actual_lat - expected_lat) < 0.000001
    ), f"Latitude mismatch: expected ~{expected_lat}, got {actual_lat}"
    assert (
        abs(actual_lon - expected_lon) < 0.000001
    ), f"Longitude mismatch: expected ~{expected_lon}, got {actual_lon}"

    # Verify altitude and error
    assert (
        found_test_location_4["altitude"] == "40.0m"
    ), f"Altitude mismatch: expected 40.0m, got {found_test_location_4['altitude']}"
    assert (
        found_test_location_4["error"] == "12.0m"
    ), f"Error mismatch: expected 12.0m, got {found_test_location_4['error']}"


@pytest.mark.web
def test_locations_add_remote(driver):
    """Test adding a location through remote interface using GPS Status marking menu"""

    # Login to remote interface
    login_to_remote(driver)

    # Get cookies from the selenium session for authentication
    cookies = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}

    # Navigate to Start menu and then to GPS Status
    press_keys_and_validate(
        driver,
        "LZLWUUUUUUURDD",
        expected_values={
            "ui_type": "UITextMenu",
            "title": "Start",
            "current_item": "GPS Status",
        },
    )

    # Enter GPS Status
    press_keys_and_validate(driver, "R", expected_values={"ui_type": "UIGPSStatus"})

    # Open marking menu with LONG+SQUARE
    press_keys_and_validate(
        driver,
        "ZS",
        expected_values={
            "ui_type": "UIMarkingMenu",
            "marking_menu_active": True,
            "underlying_ui_type": "UIGPSStatus",
        },
    )

    # Navigate to Save option (assuming it's available - may need to check actual menu structure)
    # Let's first check what marking menu options are available
    response = requests.get(
        f"{get_homepage_url()}/api/current-selection", cookies=cookies
    )
    assert response.status_code == 200
    data = response.json()

    # Check if Save option is available in marking menu
    marking_menu_options = data.get("marking_menu_options", {})
    save_option_found = False
    save_direction = None

    for direction, option in marking_menu_options.items():
        if option.get("label", "").lower() == "save":
            save_option_found = True
            save_direction = direction
            break

    if not save_option_found:
        # If Save is not available, skip this test or fail with informative message
        pytest.skip("Save option not available in GPS Status marking menu")

    # Navigate to Save option
    direction_key_map = {"up": "U", "down": "D", "left": "L", "right": "R"}

    save_key = direction_key_map.get(
        save_direction, "R"
    )  # Default to right if not found

    press_keys_and_validate(
        driver,
        save_key,
        expected_values={
            "marking_menu_active": False,
            "show_keypad": True,
            "text_entry_mode": True,
            "title": "Location Name",
            "ui_type": "UITextEntry",
        },
    )

    # Read the location name from current-selection API
    response = requests.get(
        f"{get_homepage_url()}/api/current-selection", cookies=cookies
    )
    assert response.status_code == 200
    data = response.json()

    # Extract the proposed location name from the UI
    location_name = data.get("value", "").strip()
    assert location_name, "Location name should not be empty in text entry"

    # Navigate back to main menu
    # TODO: This should be R as first character at some point. But R currently does nothing.
    press_keys(driver, "LZLWDD")  # LONG+LEFT to go to main menu

    # Now navigate to locations page
    driver.get(f"{get_homepage_url()}/locations")

    # Wait for locations table to load
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "table"))
    )

    # Check if the specific location was added using the captured name
    table_body = driver.find_element(By.TAG_NAME, "tbody")
    existing_locations = table_body.find_elements(By.TAG_NAME, "tr")

    # Look for the location with the specific name we captured
    specific_location_found = False
    found_location_data = None

    for row in existing_locations:
        cells = row.find_elements(By.TAG_NAME, "td")
        if cells and len(cells) >= 6:  # Ensure we have enough columns
            name_column = cells[0].text.strip()  # Name is the 1st column (index 0)
            if name_column.lower() == location_name.lower():
                specific_location_found = True
                found_location_data = {
                    "name": name_column,
                    "latitude": cells[1].text.strip(),
                    "longitude": cells[2].text.strip(),
                    "altitude": cells[3].text.strip(),
                    "error": cells[4].text.strip(),
                    "source": cells[5].text.strip(),
                }
                break

    # Assert that the specific location was added
    assert (
        specific_location_found
    ), f"Location '{location_name}' not found in locations table after remote save"

    # Additional verification: check that it has a GPS-related source
    assert found_location_data is not None, "Location data should not be None"
    source = found_location_data["source"].lower()
    assert (
        "gps" in source or "current" in source or "location" in source
    ), f"Expected GPS-related source, got: {found_location_data['source']}"

    # Log the found location for debugging/verification
    # Successfully found location: {found_location_data}

    # Now delete the location to clean up
    # Find the row index of the location we just verified
    location_row_index = None
    for i, row in enumerate(existing_locations):
        cells = row.find_elements(By.TAG_NAME, "td")
        if cells and len(cells) >= 6:
            name_column = cells[0].text.strip()
            if name_column.lower() == location_name.lower():
                location_row_index = i
                break

    assert (
        location_row_index is not None
    ), f"Could not find row index for location '{location_name}'"

    # Click the delete button for this location (uses loop.index0 which is the row index)
    delete_button_selector = f"a[href='#delete-modal-{location_row_index}']"
    delete_button = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, delete_button_selector))
    )
    delete_button.click()

    # Wait for delete confirmation modal to appear
    delete_modal_id = f"delete-modal-{location_row_index}"
    WebDriverWait(driver, 10).until(
        EC.visibility_of_element_located((By.ID, delete_modal_id))
    )

    # Click the actual delete button in the modal
    confirm_delete_selector = f"#delete-modal-{location_row_index} a[href='/locations/delete/{location_row_index}']"
    confirm_delete_button = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, confirm_delete_selector))
    )
    confirm_delete_button.click()
    time.sleep(1)

    # Wait for page to refresh and load the updated table
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "table"))
    )

    # Verify the location was actually deleted
    table_body_after_delete = driver.find_element(By.TAG_NAME, "tbody")
    locations_after_delete = table_body_after_delete.find_elements(By.TAG_NAME, "tr")

    # Check that the location is no longer in the table
    location_still_exists = False
    for row in locations_after_delete:
        cells = row.find_elements(By.TAG_NAME, "td")
        if cells and len(cells) >= 6:
            name_column = cells[0].text.strip()
            if name_column.lower() == location_name.lower():
                location_still_exists = True
                break

    # Assert that the location was successfully deleted
    assert (
        not location_still_exists
    ), f"Location '{location_name}' still exists in table after deletion"


@pytest.mark.web
def test_locations_default_switching(driver):
    """Test switching default locations and verifying star indicators"""
    # Login and navigate to locations page
    _login_to_interface(driver)
    driver.get(f"{get_homepage_url()}/locations")

    # Wait for table to load
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "table"))
    )

    # Find the current default location and a non-default location
    table_body = driver.find_element(By.TAG_NAME, "tbody")
    existing_locations = table_body.find_elements(By.TAG_NAME, "tr")

    # Check that there are at least two locations before proceeding
    assert (
        len(existing_locations) >= 2
    ), f"Need at least 2 locations to test default switching, found {len(existing_locations)}"

    current_default_index = None
    current_default_name = None
    non_default_index = None
    non_default_name = None

    for i, row in enumerate(existing_locations):
        cells = row.find_elements(By.TAG_NAME, "td")
        if cells and len(cells) >= 7:  # Ensure we have enough columns
            name_cell = cells[0]
            # Get only the text content, excluding icon text
            full_text = name_cell.text.strip()
            location_name = full_text.replace("star ", "").strip()  # Remove icon text

            # Check if this location has a tiny star (default indicator)
            tiny_star_icons = name_cell.find_elements(
                By.CSS_SELECTOR, "i.material-icons.tiny"
            )
            has_star = any(icon.text.strip() == "star" for icon in tiny_star_icons)

            if has_star and current_default_index is None:
                current_default_index = i
                current_default_name = location_name
            elif not has_star and non_default_index is None:
                non_default_index = i
                non_default_name = location_name

    # Ensure we found both a default and non-default location
    assert current_default_index is not None, "No default location found (no star icon)"
    assert non_default_index is not None, "No non-default location found to test with"
    assert current_default_name is not None and non_default_name is not None

    # Capture original state before making changes (to avoid stale element references later)
    def get_location_info(locations):
        info = []
        for i, row in enumerate(locations):
            cells = row.find_elements(By.TAG_NAME, "td")
            if cells and len(cells) >= 1:
                name_cell = cells[0]
                # Get only the text content, excluding icon text
                full_text = name_cell.text.strip()
                location_name = full_text.replace(
                    "star ", ""
                ).strip()  # Remove icon text
                tiny_star_icons = name_cell.find_elements(
                    By.CSS_SELECTOR, "i.material-icons.tiny"
                )
                has_star = any(icon.text.strip() == "star" for icon in tiny_star_icons)
                star_indicator = "⭐" if has_star else "  "
                info.append(f"{i}: {star_indicator} {location_name}")
        return info

    original_info = get_location_info(existing_locations)

    # Step 1: Make the non-default location the new default
    set_default_button = driver.find_element(
        By.CSS_SELECTOR, f"a[href='/locations/set_default/{non_default_index}']"
    )
    set_default_button.click()

    # Give the server time to process the change and redirect
    time.sleep(1)

    # Force refresh to ensure we have the latest state
    # driver.refresh()

    # Wait for the page to reload completely
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "table"))
    )

    # Additional wait for any dynamic content to settle
    time.sleep(1)

    # Step 2: Verify the new default location has the star
    table_body = driver.find_element(By.TAG_NAME, "tbody")
    updated_locations = table_body.find_elements(By.TAG_NAME, "tr")

    # Debug: Print locations before and after side by side
    print("\n" + "=" * 80)
    print("LOCATIONS COMPARISON (BEFORE vs AFTER SET DEFAULT)")
    print("=" * 80)

    # Get updated info (original_info was captured earlier to avoid stale elements)
    updated_info = get_location_info(updated_locations)

    # Print side by side
    max_lines = max(len(original_info), len(updated_info))
    print(f"{'BEFORE (original)':<35} | {'AFTER (updated)':<35}")
    print("-" * 35 + " | " + "-" * 35)

    for i in range(max_lines):
        left = original_info[i] if i < len(original_info) else ""
        right = updated_info[i] if i < len(updated_info) else ""
        print(f"{left:<35} | {right:<35}")

    print("=" * 80)
    print(
        f"Expected change: '{current_default_name}' lose star, '{non_default_name}' gain star"
    )
    print("=" * 80 + "\n")

    new_default_has_star = False
    old_default_lost_star = True  # Assume it lost the star until proven otherwise

    for i, row in enumerate(updated_locations):
        cells = row.find_elements(By.TAG_NAME, "td")
        if cells and len(cells) >= 7:
            name_cell = cells[0]
            # Get only the text content, excluding icon text
            full_text = name_cell.text.strip()
            location_name = full_text.replace("star ", "").strip()  # Remove icon text

            # Check if this location has a tiny star (default indicator)
            tiny_star_icons = name_cell.find_elements(
                By.CSS_SELECTOR, "i.material-icons.tiny"
            )
            has_star = any(icon.text.strip() == "star" for icon in tiny_star_icons)

            if location_name == non_default_name and has_star:
                new_default_has_star = True
            elif location_name == current_default_name and has_star:
                old_default_lost_star = False  # Old default still has star (bad)
        else:
            assert (
                False
            ), f"Table row {i, row} does not have enough cells to verify default status"

    # Assert the switch worked correctly
    assert (
        new_default_has_star
    ), f"Location '{non_default_name}' should now have the star (be default)"
    assert (
        old_default_lost_star
    ), f"Location '{current_default_name}' should no longer have the star"

    # Step 3: Switch back to the original default location
    # Find the row index of the original default location in the updated table
    original_default_new_index = None
    for i, row in enumerate(updated_locations):
        cells = row.find_elements(By.TAG_NAME, "td")
        if cells and len(cells) >= 7:
            # Get only the text content, excluding icon text
            full_text = cells[0].text.strip()
            location_name = full_text.replace("star ", "").strip()  # Remove icon text
            if location_name == current_default_name:
                original_default_new_index = i
                break

    assert (
        original_default_new_index is not None
    ), f"Could not find original default location '{current_default_name}' in updated table"

    # Click to make the original location default again
    restore_default_button = driver.find_element(
        By.CSS_SELECTOR,
        f"a[href='/locations/set_default/{original_default_new_index}']",
    )
    restore_default_button.click()

    # Give the server time to process the change and redirect
    time.sleep(1)

    # Force refresh to ensure we have the latest state
    # driver.refresh()

    # Wait for the page to reload completely
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "table"))
    )

    # Additional wait for any dynamic content to settle
    time.sleep(1)

    # Step 4: Verify we're back to the original state
    table_body = driver.find_element(By.TAG_NAME, "tbody")
    final_locations = table_body.find_elements(By.TAG_NAME, "tr")

    original_restored = False
    new_default_lost_star = True

    for i, row in enumerate(final_locations):
        cells = row.find_elements(By.TAG_NAME, "td")
        if cells and len(cells) >= 7:
            name_cell = cells[0]
            # Get only the text content, excluding icon text
            full_text = name_cell.text.strip()
            location_name = full_text.replace("star ", "").strip()  # Remove icon text

            # Check if this location has a tiny star (default indicator)
            tiny_star_icons = name_cell.find_elements(
                By.CSS_SELECTOR, "i.material-icons.tiny"
            )
            has_star = any(icon.text.strip() == "star" for icon in tiny_star_icons)

            if location_name == current_default_name and has_star:
                original_restored = True
            elif location_name == non_default_name and has_star:
                new_default_lost_star = False  # Still has star (bad)

    # Assert we're back to original state
    assert original_restored, f"Original default location '{current_default_name}' should have the star restored"
    assert (
        new_default_lost_star
    ), f"Location '{non_default_name}' should no longer have the star"


def _login_to_interface(driver):
    """Helper function to login to web interface"""
    login_to_locations(driver)

    # Check if we need to login (redirected to login page)
    try:
        # Wait briefly to see if login form appears
        WebDriverWait(driver, 2).until(
            EC.presence_of_element_located((By.ID, "password"))
        )
        # We're on the login page, use centralized login function
        login_with_password(driver)
        # Wait for redirect back to locations page after successful login
        WebDriverWait(driver, 10).until(lambda d: "/locations" in d.current_url)
    except Exception:
        # No login required, already authenticated or directly accessible
        pass


def _add_new_location(driver, location_data):
    """Helper function to add a new location"""
    # Click "Add New Location" button
    add_button = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "a[href='/locations?add_new=1']"))
    )
    add_button.click()

    # Wait for form to appear
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "location_form"))
    )

    # Fill in the form fields
    name_field = driver.find_element(By.ID, "name-location_form")
    name_field.clear()
    name_field.send_keys(location_data["name"])
    # Trigger change event for Materialize validation
    name_field.send_keys("")

    latitude_field = driver.find_element(By.ID, "latitude-location_form")
    latitude_field.clear()
    latitude_field.send_keys(location_data["latitude"])
    latitude_field.send_keys("")

    longitude_field = driver.find_element(By.ID, "longitude-location_form")
    longitude_field.clear()
    longitude_field.send_keys(location_data["longitude"])
    longitude_field.send_keys("")

    altitude_field = driver.find_element(By.ID, "altitude-location_form")
    altitude_field.clear()
    altitude_field.send_keys(location_data["altitude"])
    altitude_field.send_keys("")

    error_field = driver.find_element(By.ID, "error_in_m-location_form")
    error_field.clear()
    error_field.send_keys(location_data["error"])
    error_field.send_keys("")

    # Wait longer for validation to complete and click outside to trigger blur events
    time.sleep(0.5)
    driver.find_element(By.TAG_NAME, "body").click()
    time.sleep(1.0)

    # Check for validation errors before submitting
    validation_errors = []

    # Check for helper text elements that indicate validation errors
    helper_texts = driver.find_elements(By.CSS_SELECTOR, "#location_form .helper-text")
    for helper_text in helper_texts:
        if helper_text.text.strip() and "red-text" in helper_text.get_attribute(
            "class"
        ):
            validation_errors.append(helper_text.text.strip())

    # Check for invalid field classes
    invalid_fields = driver.find_elements(
        By.CSS_SELECTOR, "#location_form input.invalid"
    )
    for field in invalid_fields:
        field_id = field.get_attribute("id")
        validation_errors.append(f"Field {field_id} is marked as invalid")

    # Check if save button is disabled (indicates validation issues)
    save_button = driver.find_element(By.ID, "saveButton-location_form")
    if save_button.get_attribute("disabled"):
        validation_errors.append("Save button is disabled due to validation errors")

    # If there are validation errors, report them
    if validation_errors:
        raise AssertionError(
            f"Form validation errors for location '{location_data['name']}': {validation_errors}"
        )

    # Submit the form by triggering the actual form submission
    form = driver.find_element(By.ID, "location_form")

    # Option 1: Try submitting the form directly
    try:
        driver.execute_script("arguments[0].submit();", form)
        time.sleep(2.0)
    except Exception:
        # Option 2: If direct submit doesn't work, try clicking the button
        try:
            save_button.click()
            time.sleep(2.0)
        except Exception:
            # Option 3: JavaScript click as last resort
            driver.execute_script("arguments[0].click();", save_button)
            time.sleep(2.0)

    # Wait for redirect or page change - be more flexible about what we wait for
    try:
        # First, try to wait for URL change
        WebDriverWait(driver, 8).until(lambda d: "add_new" not in d.current_url)
    except Exception:
        # If URL doesn't change, wait for form to disappear
        try:
            WebDriverWait(driver, 5).until_not(
                EC.presence_of_element_located((By.ID, "location_form"))
            )
        except Exception:
            # If form is still there, just proceed and check if location was added
            pass

    # Navigate back to locations page to ensure we're in the right state
    driver.get(f"{get_homepage_url()}/locations")

    # Wait for the table to be present in final state
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "table"))
    )
