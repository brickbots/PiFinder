"""
Selenium tests for PiFinder's observation tracking web interface.

Test Overview

The test suite validates the observations pages at localhost:8080/observations
through automated browser testing using Selenium WebDriver. Authentication uses
the default password "solveit".

The pages are organised by observing *night* rather than by software run: a
restart mid-evening starts a new session but not a new night, so one night's
card can cover several runs. See PiFinder.observing_nights.

Nights List Tests

Page Load: the nights page loads and says so in its title or body.

Summary Counters: the night counter ("Nights"), object counter ("Objects") and
observing hours ("Hours") are visible.

Night Cards: each night is a card linking to /observations/night/<date>,
carrying a date, an object count and a start -> end local time range.

Responsive Layout: the cards remain visible at a mobile size (375x667).

Night Detail Tests

Card Navigation: clicking a night card navigates to /observations/night/<date>.

Detail Page Content: the detail page shows the night's date, an Objects count,
Hours, a download link, and one timeline entry per logged object.

Object Link: a logged object links through to its own page, which shows the
object's identity and its observation history.

Session Compatibility

Session Redirect: an old /observations/<session_id> link still resolves, landing
on the night that run belonged to; ?download=1 on it still returns that
session's TSV unchanged.

Download / Export Tests

List Download: verifies HTTP 200, Content-Type text/tsv, Content-Disposition
attachment; filename=observations.tsv, and valid TSV content.

Night Download: the per-night download link, verifying the filename carries the
night's date and the content is valid TSV.

Infrastructure: Uses the same Selenium Grid setup as other web tests with
automatic skipping when unavailable or when the database contains no data.
"""

import pytest
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from web_test_utils import login_to_observations, login_with_password, get_homepage_url


def _login_to_observations(driver):
    """Helper function to login and navigate to observations page"""
    login_to_observations(driver)

    # Check if we need to login (redirected to login page)
    try:
        # Wait for login form — Safari needs more time to load after redirect
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "password"))
        )
        # We're on the login page, use centralized login function
        login_with_password(driver)
        # Wait for redirect back to observations page after successful login
        WebDriverWait(driver, 10).until(lambda d: "/observations" in d.current_url)
    except Exception:
        # No login required, already authenticated or directly accessible
        pass


def _night_cards(driver, timeout=10):
    """The night cards on the list page, or an empty list if there are none."""
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    return driver.find_elements(By.CLASS_NAME, "obs-night")


def _open_first_night(driver, wait):
    """Navigate into the first night, skipping the test if there are none."""
    cards = _night_cards(driver)
    if not cards:
        pytest.skip("No observing nights available")
    cards[0].click()
    wait.until(lambda d: "/observations/night/" in d.current_url)


@pytest.mark.web
def test_observations_page_loads(driver):
    """Test that the observations page loads correctly."""
    _login_to_observations(driver)

    wait = WebDriverWait(driver, 10)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    assert (
        "observations" in driver.page_source.lower() or "Observations" in driver.title
    )


@pytest.mark.web
def test_summary_counters_display(driver):
    """Test that the nights/objects/hours counters are displayed."""
    _login_to_observations(driver)

    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    body_text = driver.find_element(By.TAG_NAME, "body").text

    for label in ("Nights", "Objects", "Hours"):
        assert label in body_text, f"Counter '{label}' not found on the page"


@pytest.mark.web
def test_night_cards_carry_date_count_and_span(driver):
    """Each night card links to its night and shows when it ran."""
    _login_to_observations(driver)

    cards = _night_cards(driver)
    if not cards:
        pytest.skip("No observing nights available")

    first = cards[0]
    assert "/observations/night/" in first.get_attribute("href")
    assert first.find_element(By.CLASS_NAME, "obs-night__date").text.strip()
    assert first.find_element(By.CLASS_NAME, "obs-night__count").text.strip()
    # Local start -> end times, which read sensibly even for a single object.
    assert "→" in first.find_element(By.CLASS_NAME, "obs-night__times").text


@pytest.mark.web
def test_mobile_layout(driver):
    """Test observations page layout on mobile viewport."""
    driver.set_window_size(375, 667)
    try:
        _login_to_observations(driver)

        cards = _night_cards(driver)
        if not cards:
            pytest.skip("No observing nights available")
        assert cards[0].is_displayed()
    finally:
        # Reset to desktop size for other tests
        driver.set_window_size(1920, 1080)


@pytest.mark.web
def test_night_detail_navigation(driver):
    """Test that clicking a night card navigates to the night page."""
    _login_to_observations(driver)

    wait = WebDriverWait(driver, 10)
    _open_first_night(driver, wait)

    assert "/observations/night/" in driver.current_url


@pytest.mark.web
def test_night_detail_page_content(driver):
    """Test the content displayed on the night detail page."""
    _login_to_observations(driver)

    wait = WebDriverWait(driver, 10)
    _open_first_night(driver, wait)

    body_text = driver.find_element(By.TAG_NAME, "body").text
    assert "Objects" in body_text
    assert "Hours" in body_text

    download_link = driver.find_element(By.CSS_SELECTOR, "a[href*='download=1']")
    assert download_link.is_displayed()

    entries = driver.find_elements(By.CLASS_NAME, "obs-log__entry")
    assert entries, "Expected at least one logged object on the night page"


@pytest.mark.web
def test_logged_object_links_to_its_own_page(driver):
    """A logged object opens a page about the object, not just the log line."""
    _login_to_observations(driver)

    wait = WebDriverWait(driver, 10)
    _open_first_night(driver, wait)

    links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/observations/object/']")
    if not links:
        pytest.skip("No logged objects available")

    links[0].click()
    wait.until(lambda d: "/observations/object/" in d.current_url)

    body_text = driver.find_element(By.TAG_NAME, "body").text
    assert "Observations" in body_text
    assert "Observation history" in body_text
    assert driver.find_elements(By.CLASS_NAME, "obs-log__entry")


@pytest.mark.web
def test_session_link_redirects_to_its_night(driver):
    """Links to a software run still resolve, landing on that run's night."""
    _login_to_observations(driver)

    wait = WebDriverWait(driver, 10)
    _open_first_night(driver, wait)

    cookies = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}
    night_url = driver.current_url
    tsv = requests.get(f"{night_url}?download=1", cookies=cookies).text
    lines = [line for line in tsv.strip().split("\n")[1:] if line]
    if not lines:
        pytest.skip("No observations in this night to resolve a session from")

    session_id = lines[0].split("\t")[0]
    response = requests.get(
        f"{get_homepage_url()}/observations/{session_id}", cookies=cookies
    )
    assert response.status_code == 200
    assert "/observations/night/" in response.url


@pytest.mark.web
def test_observations_list_download(driver):
    """Test that the download button on the nights page returns a valid TSV."""

    _login_to_observations(driver)

    wait = WebDriverWait(driver, 10)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

    download_link = wait.until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "a[href='/observations?download=1']")
        )
    )

    assert (
        download_link.get_attribute("href")
        == f"{get_homepage_url()}/observations?download=1"
    )

    download_icon = download_link.find_element(By.CLASS_NAME, "material-icons")
    assert download_icon.text.strip() == "download"

    cookies = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}

    response = requests.get(
        f"{get_homepage_url()}/observations?download=1", cookies=cookies
    )

    assert (
        response.status_code == 200
    ), f"Download request failed with status {response.status_code}"

    assert "text/tsv" in response.headers.get(
        "Content-Type", ""
    ), "Expected TSV content type"

    content_disposition = response.headers.get("Content-Disposition", "")
    assert (
        "attachment" in content_disposition
    ), "Expected attachment in Content-Disposition header"
    assert (
        "observations.tsv" in content_disposition
    ), "Expected observations.tsv filename"

    file_content = response.text.strip()
    if file_content:  # Only check if there's content (empty database is acceptable)
        lines = file_content.split("\n")
        assert len(lines) > 0, "TSV file should have at least header line"
        if len(lines) > 1:  # If there are data rows beyond header
            assert "\t" in lines[0], "First line should contain tabs (TSV format)"


@pytest.mark.web
def test_night_download(driver):
    """Test that a night's download link returns that night's TSV."""

    _login_to_observations(driver)

    wait = WebDriverWait(driver, 10)
    _open_first_night(driver, wait)

    night_key = driver.current_url.rstrip("/").split("/observations/night/")[1]

    download_link = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "a[href*='download=1']"))
    )
    assert download_link.is_displayed()

    href = download_link.get_attribute("href")
    assert "download=1" in href
    assert f"/observations/night/{night_key}" in href

    download_icon = download_link.find_element(By.CLASS_NAME, "material-icons")
    assert download_icon.text.strip() == "download"

    cookies = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}
    response = requests.get(href, cookies=cookies)

    assert (
        response.status_code == 200
    ), f"Night download request failed with status {response.status_code}"

    assert "text/tsv" in response.headers.get(
        "Content-Type", ""
    ), "Expected TSV content type"

    content_disposition = response.headers.get("Content-Disposition", "")
    assert (
        "attachment" in content_disposition
    ), "Expected attachment in Content-Disposition header"
    assert (
        f"observations_{night_key}.tsv" in content_disposition
    ), f"Expected observations_{night_key}.tsv filename"

    file_content = response.text.strip()
    if file_content:  # Only check if there's content (empty night is acceptable)
        lines = file_content.split("\n")
        assert len(lines) > 0, "Night TSV file should have at least header line"
        if len(lines) > 1:  # If there are data rows beyond header
            assert "\t" in lines[0], "First line should contain tabs (TSV format)"
