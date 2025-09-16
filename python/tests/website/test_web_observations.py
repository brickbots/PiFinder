"""
Test the observations page functionality.
"""

import pytest
import os
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from web_test_utils import login_to_observations, login_with_password


def _login_to_observations(driver):
    """Helper function to login and navigate to observations page"""
    login_to_observations(driver)
    
    # Check if we need to login (redirected to login page)
    try:
        # Wait briefly to see if login form appears
        WebDriverWait(driver, 2).until(
            EC.presence_of_element_located((By.ID, "password"))
        )
        # We're on the login page, use centralized login function  
        login_with_password(driver)
        # Wait for redirect back to observations page after successful login
        WebDriverWait(driver, 10).until(lambda d: "/observations" in d.current_url)
    except Exception:
        # No login required, already authenticated or directly accessible
        pass


@pytest.mark.web
def test_observations_page_loads(driver):
    """Test that the observations page loads correctly."""
    _login_to_observations(driver)

    # Verify page loads with expected title or header
    wait = WebDriverWait(driver, 10)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    assert (
        "observations" in driver.page_source.lower() or "Observations" in driver.title
    )


@pytest.mark.web
def test_session_counter_display(driver):
    """Test that Session counter is displayed."""
    _login_to_observations(driver)

    # Look for session counter element
    wait = WebDriverWait(driver, 10)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    body_text = driver.find_element(By.TAG_NAME, "body").text
    assert "Sessions" in body_text or "session" in body_text


@pytest.mark.web
def test_observation_counter_display(driver):
    """Test that Observation Counter is displayed."""
    _login_to_observations(driver)

    # Look for observation counter element
    wait = WebDriverWait(driver, 10)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    body_text = driver.find_element(By.TAG_NAME, "body").text
    assert "Objects" in body_text


@pytest.mark.web
def test_total_hours_display(driver):
    """Test that Total Hours display is present."""
    _login_to_observations(driver)

    # Look for total hours element
    wait = WebDriverWait(driver, 10)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    body_text = driver.find_element(By.TAG_NAME, "body").text
    assert "Total Hours" in body_text


@pytest.mark.web
def test_observations_table_headers(driver):
    """Test that observations table exists with correct headers."""
    _login_to_observations(driver)

    # Wait for table to load
    wait = WebDriverWait(driver, 10)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))

    # Check for required headers
    required_headers = ["Date", "Location", "Hours", "objects"]

    # Get all table headers
    headers = driver.find_elements(By.TAG_NAME, "th")
    header_texts = [header.text.strip() for header in headers]

    # Verify each required header is present
    for required_header in required_headers:
        assert any(
            required_header.lower() in header_text.lower()
            for header_text in header_texts
        ), f"Header '{required_header}' not found in table headers: {header_texts}"


@pytest.mark.web
def test_observations_table_structure(driver):
    """Test that observations table has proper structure."""
    _login_to_observations(driver)

    # Wait for table to load
    wait = WebDriverWait(driver, 10)
    table = wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))

    # Verify table has rows with headers
    rows = table.find_elements(By.TAG_NAME, "tr")
    assert len(rows) >= 1, "Table should have at least one row for headers"

    # Check that first row contains header cells
    first_row = rows[0]
    headers = first_row.find_elements(By.TAG_NAME, "th")
    assert len(headers) >= 4, f"Expected at least 4 header cells, found {len(headers)}"


@pytest.mark.web
def test_mobile_layout(driver):
    """Test observations page layout on mobile viewport."""
    driver.set_window_size(375, 667)
    _login_to_observations(driver)

    # Verify page elements are visible in mobile layout
    wait = WebDriverWait(driver, 10)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

    # Check that table adapts to mobile layout
    table = driver.find_element(By.TAG_NAME, "table")
    assert table.is_displayed()

    # Reset to desktop size for other tests
    driver.set_window_size(1920, 1080)


@pytest.mark.web
def test_session_detail_navigation(driver):
    """Test that clicking on a table row navigates to session detail page."""
    _login_to_observations(driver)

    wait = WebDriverWait(driver, 10)
    table = wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))

    # Find data rows (skip header row)
    rows = table.find_elements(By.TAG_NAME, "tr")
    data_rows = [row for row in rows if row.find_elements(By.TAG_NAME, "td")]

    if len(data_rows) > 0:
        # Click on the first data row
        first_data_row = data_rows[0]
        first_data_row.click()

        # Wait for navigation to detail page
        wait.until(
            lambda d: "/observations/" in d.current_url
            and d.current_url != "http://localhost:8080/observations"
        )

        # Verify we're on a detail page
        assert "/observations/" in driver.current_url
        assert driver.current_url != "http://localhost:8080/observations"
    else:
        # No data rows to click - this is acceptable for empty database
        pytest.skip("No observation sessions available to test detail navigation")


@pytest.mark.web
def test_session_detail_page_content(driver):
    """Test the content displayed on the session detail page."""
    _login_to_observations(driver)

    wait = WebDriverWait(driver, 10)
    table = wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))

    # Find data rows (skip header row)
    rows = table.find_elements(By.TAG_NAME, "tr")
    data_rows = [row for row in rows if row.find_elements(By.TAG_NAME, "td")]

    if len(data_rows) > 0:
        # Click on the first data row to navigate to detail page
        first_data_row = data_rows[0]
        first_data_row.click()

        # Wait for navigation to detail page
        wait.until(
            lambda d: "/observations/" in d.current_url
            and d.current_url != "http://localhost:8080/observations"
        )

        # Test session detail page content
        body_text = driver.find_element(By.TAG_NAME, "body").text

        # Check for session header
        assert "Observing Session" in body_text

        # Check for Objects counter
        assert "Objects" in body_text

        # Check for Hours display
        assert "Hours" in body_text

        # Check for download link (material icon)
        download_link = driver.find_element(By.CSS_SELECTOR, "a[href*='download=1']")
        assert download_link.is_displayed()

        # Check for observations table with correct headers
        detail_table = driver.find_element(By.TAG_NAME, "table")
        headers = detail_table.find_elements(By.TAG_NAME, "th")
        header_texts = [header.text.strip() for header in headers]

        required_headers = ["Time", "Catalog", "Sequence", "Notes"]
        for required_header in required_headers:
            assert any(
                required_header.lower() in header_text.lower()
                for header_text in header_texts
            ), f"Header '{required_header}' not found in detail table headers: {header_texts}"

    else:
        # No data rows to click - this is acceptable for empty database
        pytest.skip("No observation sessions available to test detail page content")


@pytest.mark.web
def test_session_detail_table_structure(driver):
    """Test the structure of the observations detail table."""
    _login_to_observations(driver)

    wait = WebDriverWait(driver, 10)
    table = wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))

    # Find data rows (skip header row)
    rows = table.find_elements(By.TAG_NAME, "tr")
    data_rows = [row for row in rows if row.find_elements(By.TAG_NAME, "td")]

    if len(data_rows) > 0:
        # Click on the first data row to navigate to detail page
        first_data_row = data_rows[0]
        first_data_row.click()

        # Wait for navigation to detail page
        wait.until(
            lambda d: "/observations/" in d.current_url
            and d.current_url != "http://localhost:8080/observations"
        )

        # Test detail table structure
        detail_table = driver.find_element(By.TAG_NAME, "table")
        detail_rows = detail_table.find_elements(By.TAG_NAME, "tr")

        # Should have at least header row
        assert (
            len(detail_rows) >= 1
        ), "Detail table should have at least one row for headers"

        # Check that first row contains header cells
        first_row = detail_rows[0]
        headers = first_row.find_elements(By.TAG_NAME, "th")
        assert (
            len(headers) == 4
        ), f"Expected 4 header cells (Time, Catalog, Sequence, Notes), found {len(headers)}"

    else:
        # No data rows to click - this is acceptable for empty database
        pytest.skip("No observation sessions available to test detail table structure")


@pytest.mark.web
def test_observations_list_download(driver):
    """Test that clicking download button on observations list page downloads a valid TSV file."""
    import requests

    _login_to_observations(driver)

    wait = WebDriverWait(driver, 10)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

    # Find the download link on the observations list page
    download_link = wait.until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "a[href='/observations?download=1']")
        )
    )

    # Verify the download link has the correct href
    assert (
        download_link.get_attribute("href")
        == "http://localhost:8080/observations?download=1"
    )

    # Check that the download icon is present (material-icons)
    download_icon = download_link.find_element(By.CLASS_NAME, "material-icons")
    assert download_icon.text.strip() == "download"

    # Get cookies from the selenium session for authentication
    cookies = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}

    # Make a direct request to download the file
    response = requests.get(
        "http://localhost:8080/observations?download=1", cookies=cookies
    )

    # Verify the response
    assert (
        response.status_code == 200
    ), f"Download request failed with status {response.status_code}"

    # Check content type header
    assert "text/tsv" in response.headers.get(
        "Content-Type", ""
    ), "Expected TSV content type"

    # Check content disposition header (should indicate file download)
    content_disposition = response.headers.get("Content-Disposition", "")
    assert (
        "attachment" in content_disposition
    ), "Expected attachment in Content-Disposition header"
    assert (
        "observations.tsv" in content_disposition
    ), "Expected observations.tsv filename"

    # Verify file content is not empty and looks like TSV
    file_content = response.text.strip()
    if file_content:  # Only check if there's content (empty database is acceptable)
        lines = file_content.split("\n")
        assert len(lines) > 0, "TSV file should have at least header line"
        # Check that it's tab-separated (TSV format)
        if len(lines) > 1:  # If there are data rows beyond header
            assert "\t" in lines[0], "First line should contain tabs (TSV format)"


@pytest.mark.web
def test_observation_detail_download(driver):
    """Test that clicking download button on observation detail page downloads a valid session TSV file."""
    import requests

    _login_to_observations(driver)

    wait = WebDriverWait(driver, 10)
    table = wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))

    # Find data rows (skip header row)
    rows = table.find_elements(By.TAG_NAME, "tr")
    data_rows = [row for row in rows if row.find_elements(By.TAG_NAME, "td")]

    if len(data_rows) > 0:
        # Click on the first data row to navigate to detail page
        first_data_row = data_rows[0]
        first_data_row.click()

        # Wait for navigation to detail page
        wait.until(
            lambda d: "/observations/" in d.current_url
            and d.current_url != "http://localhost:8080/observations"
        )

        # Find the download link on the detail page
        download_link = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "a[href*='download=1']"))
        )

        # Verify download link is displayed and has correct attributes
        assert download_link.is_displayed()

        # Get the href to verify it contains the session ID and download parameter
        href = download_link.get_attribute("href")
        assert "download=1" in href
        assert "/observations/" in href

        # Extract session ID from URL for testing
        session_id = href.split("/observations/")[1].split("?")[0]

        # Check that the download icon is present (material-icons)
        download_icon = download_link.find_element(By.CLASS_NAME, "material-icons")
        assert download_icon.text.strip() == "download"

        # Get cookies from the selenium session for authentication
        cookies = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}

        # Make a direct request to download the session file
        response = requests.get(href, cookies=cookies)

        # Verify the response
        assert (
            response.status_code == 200
        ), f"Session download request failed with status {response.status_code}"

        # Check content type header
        assert "text/tsv" in response.headers.get(
            "Content-Type", ""
        ), "Expected TSV content type"

        # Check content disposition header (should indicate file download with session ID)
        content_disposition = response.headers.get("Content-Disposition", "")
        assert (
            "attachment" in content_disposition
        ), "Expected attachment in Content-Disposition header"
        assert (
            f"observations_{session_id}.tsv" in content_disposition
        ), f"Expected observations_{session_id}.tsv filename"

        # Verify file content is not empty and looks like TSV
        file_content = response.text.strip()
        if file_content:  # Only check if there's content (empty session is acceptable)
            lines = file_content.split("\n")
            assert len(lines) > 0, "Session TSV file should have at least header line"
            # Check that it's tab-separated (TSV format)
            if len(lines) > 1:  # If there are data rows beyond header
                assert "\t" in lines[0], "First line should contain tabs (TSV format)"

        # The page should remain on the detail page after download
        assert "/observations/" in driver.current_url

    else:
        # No data rows to click - this is acceptable for empty database
        pytest.skip("No observation sessions available to test detail download")
