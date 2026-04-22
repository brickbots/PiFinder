"""
Tests for features ported from server.py to server2.py:
- ALT_SQUARE button in key_callback
- restart_pifinder template rendering (via tools/restore)
"""

import io
import zipfile
import pytest
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from web_test_utils import get_homepage_url, navigate_to_page, login_with_password


def _authenticated_cookies(driver):
    """Navigate to tools (triggers login) and return session cookies."""
    navigate_to_page(driver, "/tools")
    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.ID, "password"))
        )
        login_with_password(driver)
        WebDriverWait(driver, 10).until(EC.url_contains("/tools"))
    except Exception:
        pass  # Already logged in
    return {c["name"]: c["value"] for c in driver.get_cookies()}


def _make_minimal_zip() -> bytes:
    """Return a minimal in-memory zip with the directory structure expected by restore_userdata."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("home/pifinder/PiFinder_data/.keep", "")
    return buf.getvalue()


@pytest.mark.web
def test_alt_square_button_in_key_callback(driver):
    """ALT_SQUARE must be accepted by /key_callback and return success."""
    cookies = _authenticated_cookies(driver)
    response = requests.post(
        f"{get_homepage_url()}/key_callback",
        json={"button": "ALT_SQUARE"},
        cookies=cookies,
    )
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )
    data = response.json()
    assert data.get("message") == "success", f"Unexpected response: {data}"


@pytest.mark.web
def test_restart_pifinder_template_renders(driver):
    """POSTing to /tools/restore must render restart_pifinder.html without error."""
    cookies = _authenticated_cookies(driver)
    zip_bytes = _make_minimal_zip()
    response = requests.post(
        f"{get_homepage_url()}/tools/restore",
        files={"backup_file": ("PiFinder_backup.zip", zip_bytes, "application/zip")},
        cookies=cookies,
    )
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text[:200]}"
    )
    assert "Restarting PiFinder" in response.text, (
        "Expected restart_pifinder.html content in response"
    )
