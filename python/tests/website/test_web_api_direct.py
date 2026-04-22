"""
Direct API tests for server.py endpoints.

Covers:
- /key_callback for every named button in Server.button_dict
- /image (unauthenticated PNG endpoint)
- /api/current-selection
- /logs/stream
- /logs/configs
- /logs/switch_config  (invalid-input rejection)
- /logs/upload_config  (invalid-input rejection)
- /tools/restore       (minimal-zip round-trip)
- Auth guard: protected endpoints redirect unauthenticated callers
"""

import io
import zipfile
import pytest
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from web_test_utils import get_homepage_url, navigate_to_page, login_with_password


# ── helpers ───────────────────────────────────────────────────────────────────


def _authenticated_cookies(driver):
    """Navigate to tools (triggers login if needed) and return session cookies."""
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


# ── /key_callback – one test per named button ─────────────────────────────────

ALL_BUTTON_NAMES = [
    "PLUS",
    "MINUS",
    "SQUARE",
    "LEFT",
    "UP",
    "DOWN",
    "RIGHT",
    "ALT_PLUS",
    "ALT_MINUS",
    "ALT_LEFT",
    "ALT_UP",
    "ALT_DOWN",
    "ALT_RIGHT",
    "ALT_0",
    "ALT_SQUARE",
    "LNG_LEFT",
    "LNG_UP",
    "LNG_DOWN",
    "LNG_RIGHT",
    "LNG_SQUARE",
]


@pytest.mark.web
@pytest.mark.parametrize("button", ALL_BUTTON_NAMES)
def test_key_callback_button(driver, button):
    """Every named button must be accepted by /key_callback and return success."""
    cookies = _authenticated_cookies(driver)
    response = requests.post(
        f"{get_homepage_url()}/key_callback",
        json={"button": button},
        cookies=cookies,
    )
    assert response.status_code == 200, (
        f"Expected 200 for button '{button}', got {response.status_code}: {response.text}"
    )
    assert response.json().get("message") == "success", (
        f"Unexpected response for button '{button}': {response.json()}"
    )


# ── /image ────────────────────────────────────────────────────────────────────


@pytest.mark.web
def test_image_endpoint_returns_png(driver):
    """/image must return 200 with image/png content without authentication."""
    response = requests.get(f"{get_homepage_url()}/image")
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}"
    )
    assert "image/png" in response.headers.get("Content-Type", ""), (
        f"Expected image/png, got {response.headers.get('Content-Type')}"
    )
    assert len(response.content) > 0, "Image response body must not be empty"


# ── /api/current-selection ────────────────────────────────────────────────────


@pytest.mark.web
def test_api_current_selection_returns_json(driver):
    """/api/current-selection must return 200 with a JSON object when authenticated."""
    cookies = _authenticated_cookies(driver)
    response = requests.get(
        f"{get_homepage_url()}/api/current-selection",
        cookies=cookies,
    )
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text[:200]}"
    )
    data = response.json()
    assert isinstance(data, dict), f"Expected a JSON object, got {type(data)}"


# ── /logs/stream ──────────────────────────────────────────────────────────────


@pytest.mark.web
def test_logs_stream_returns_json(driver):
    """/logs/stream must return 200 with 'logs' and 'position' keys."""
    cookies = _authenticated_cookies(driver)
    response = requests.get(
        f"{get_homepage_url()}/logs/stream",
        params={"position": 0},
        cookies=cookies,
    )
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text[:200]}"
    )
    data = response.json()
    assert "logs" in data, f"Missing 'logs' key in response: {data}"
    assert "position" in data, f"Missing 'position' key in response: {data}"
    assert isinstance(data["logs"], list), "'logs' must be a list"


# ── /logs/configs ─────────────────────────────────────────────────────────────


@pytest.mark.web
def test_logs_configs_returns_json(driver):
    """/logs/configs must return 200 with a 'configs' list."""
    cookies = _authenticated_cookies(driver)
    response = requests.get(
        f"{get_homepage_url()}/logs/configs",
        cookies=cookies,
    )
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text[:200]}"
    )
    data = response.json()
    assert "configs" in data, f"Missing 'configs' key in response: {data}"
    assert isinstance(data["configs"], list), "'configs' must be a list"


# ── /logs/switch_config ───────────────────────────────────────────────────────


@pytest.mark.web
def test_logs_switch_config_rejects_invalid_filename(driver):
    """/logs/switch_config must return error JSON for a filename that doesn't match logconf_*.json."""
    cookies = _authenticated_cookies(driver)
    response = requests.post(
        f"{get_homepage_url()}/logs/switch_config",
        data={"logconf_file": "evil.json"},
        cookies=cookies,
    )
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text[:200]}"
    )
    data = response.json()
    assert data.get("status") == "error", (
        f"Expected error status for invalid filename, got: {data}"
    )


@pytest.mark.web
def test_logs_switch_config_rejects_nonexistent_file(driver):
    """/logs/switch_config must return error JSON for a file that does not exist on disk."""
    cookies = _authenticated_cookies(driver)
    response = requests.post(
        f"{get_homepage_url()}/logs/switch_config",
        data={"logconf_file": "logconf_nonexistent_xyzzy.json"},
        cookies=cookies,
    )
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text[:200]}"
    )
    data = response.json()
    assert data.get("status") == "error", (
        f"Expected error status for missing file, got: {data}"
    )


# ── /logs/upload_config ───────────────────────────────────────────────────────


@pytest.mark.web
def test_logs_upload_config_rejects_bad_filename(driver):
    """/logs/upload_config must reject uploads whose filename does not match logconf_*.json."""
    cookies = _authenticated_cookies(driver)
    response = requests.post(
        f"{get_homepage_url()}/logs/upload_config",
        files={"config_file": ("bad_name.json", b"{}", "application/json")},
        cookies=cookies,
    )
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text[:200]}"
    )
    data = response.json()
    assert data.get("status") == "error", (
        f"Expected error status for bad filename, got: {data}"
    )


@pytest.mark.web
def test_logs_upload_config_rejects_missing_file(driver):
    """/logs/upload_config must return error JSON when no file is uploaded."""
    cookies = _authenticated_cookies(driver)
    response = requests.post(
        f"{get_homepage_url()}/logs/upload_config",
        cookies=cookies,
    )
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text[:200]}"
    )
    data = response.json()
    assert data.get("status") == "error", (
        f"Expected error status when no file provided, got: {data}"
    )


# ── /tools/restore ────────────────────────────────────────────────────────────


@pytest.mark.web
def test_tools_restore_renders_restart_page(driver):
    """POSTing a valid backup zip to /tools/restore must render restart_pifinder.html."""
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


# ── /logs/download ────────────────────────────────────────────────────────────


@pytest.mark.web
def test_logs_download_returns_zip(driver):
    """/logs/download must return 200 with a non-empty application/zip body."""
    cookies = _authenticated_cookies(driver)
    response = requests.get(
        f"{get_homepage_url()}/logs/download",
        cookies=cookies,
    )
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text[:200]}"
    )
    assert "zip" in response.headers.get("Content-Type", ""), (
        f"Expected zip content-type, got {response.headers.get('Content-Type')}"
    )
    assert len(response.content) > 0, "Zip response body must not be empty"


# ── /tools/backup ─────────────────────────────────────────────────────────────


@pytest.mark.web
def test_tools_backup_returns_zip(driver):
    """/tools/backup must return 200 with a non-empty application/zip body."""
    cookies = _authenticated_cookies(driver)
    response = requests.get(
        f"{get_homepage_url()}/tools/backup",
        cookies=cookies,
    )
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text[:200]}"
    )
    assert "zip" in response.headers.get("Content-Type", ""), (
        f"Expected zip content-type, got {response.headers.get('Content-Type')}"
    )
    assert len(response.content) > 0, "Backup zip body must not be empty"


# ── /system/restart and /system/restart_pifinder ─────────────────────────────


@pytest.mark.web
def test_system_restart_requires_auth(driver):
    """/system/restart must redirect unauthenticated callers (not trigger a real restart)."""
    response = requests.get(
        f"{get_homepage_url()}/system/restart",
        allow_redirects=False,
    )
    assert response.status_code in (302, 401), (
        f"Expected redirect for unauthenticated /system/restart, got {response.status_code}"
    )


@pytest.mark.web
def test_system_restart_pifinder_requires_auth(driver):
    """/system/restart_pifinder must redirect unauthenticated callers."""
    response = requests.get(
        f"{get_homepage_url()}/system/restart_pifinder",
        allow_redirects=False,
    )
    assert response.status_code in (302, 401), (
        f"Expected redirect for unauthenticated /system/restart_pifinder, got {response.status_code}"
    )


# ── /gps/update ───────────────────────────────────────────────────────────────


@pytest.mark.web
def test_gps_update_redirects_to_home(driver):
    """Authenticated POST /gps/update with valid coordinates must redirect to /."""
    cookies = _authenticated_cookies(driver)
    response = requests.post(
        f"{get_homepage_url()}/gps/update",
        data={"latitudeDecimal": "51.5", "longitudeDecimal": "-0.1", "altitude": "10"},
        cookies=cookies,
        allow_redirects=False,
    )
    assert response.status_code == 302, (
        f"Expected 302 redirect, got {response.status_code}: {response.text[:200]}"
    )


# ── auth guards ───────────────────────────────────────────────────────────────


@pytest.mark.web
@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("post", "/key_callback", {"json": {"button": "UP"}}),
        ("get", "/api/current-selection", {}),
        ("get", "/logs/stream", {}),
        ("get", "/logs/configs", {}),
        ("post", "/logs/switch_config", {"data": {"logconf_file": "logconf_x.json"}}),
        ("post", "/logs/upload_config", {}),
        ("post", "/tools/restore", {}),
        ("get", "/logs/download", {}),
        ("get", "/tools/backup", {}),
        ("get", "/system/restart", {}),
        ("get", "/system/restart_pifinder", {}),
        ("post", "/gps/update", {"data": {"latitudeDecimal": "0", "longitudeDecimal": "0", "altitude": "0"}}),
    ],
)
def test_protected_endpoint_requires_auth(driver, method, path, kwargs):
    """Protected endpoints must redirect or reject unauthenticated callers."""
    fn = getattr(requests, method)
    response = fn(
        f"{get_homepage_url()}{path}",
        allow_redirects=False,
        **kwargs,
    )
    assert response.status_code in (302, 401), (
        f"{method.upper()} {path} should require auth, got {response.status_code}"
    )
