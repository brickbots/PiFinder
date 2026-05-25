from unittest.mock import patch, MagicMock

import pytest
import requests

from PiFinder.ui.software import (
    update_needed,
    _strip_markdown,
    _fetch_migration_config,
    _UNLOCK_SEQUENCE,
)


_NIXOS_URL = "https://example.invalid/pifinder-nixos.tar.zst"


@pytest.mark.unit
class TestUpdateNeeded:
    def test_newer_version_available(self):
        assert update_needed("2.3.0", "2.4.0") is True

    def test_same_version(self):
        assert update_needed("2.4.0", "2.4.0") is False

    def test_older_version(self):
        assert update_needed("2.5.0", "2.4.0") is False

    def test_major_version_bump(self):
        assert update_needed("1.9.9", "2.0.0") is True

    def test_patch_bump(self):
        assert update_needed("2.4.0", "2.4.1") is True

    def test_garbage_input_returns_true(self):
        assert update_needed("garbage", "2.4.0") is True

    def test_empty_string_returns_true(self):
        assert update_needed("", "") is True

    def test_partial_version_returns_true(self):
        assert update_needed("2.4", "2.5.0") is True

    def test_unknown_returns_true(self):
        assert update_needed("2.4.0", "Unknown") is True


@pytest.mark.unit
class TestUnlockSequence:
    def test_sequence_length(self):
        assert len(_UNLOCK_SEQUENCE) == 7

    def test_sequence_content(self):
        assert _UNLOCK_SEQUENCE == ["square"] * 7


@pytest.mark.unit
class TestStripMarkdown:
    def test_removes_headings(self):
        assert _strip_markdown("# Hello") == "Hello"
        assert _strip_markdown("## Sub") == "Sub"

    def test_removes_bold(self):
        assert _strip_markdown("**bold**") == "bold"

    def test_removes_italic(self):
        assert _strip_markdown("*italic*") == "italic"

    def test_removes_links(self):
        assert _strip_markdown("[text](http://example.com)") == "text"

    def test_removes_backticks(self):
        assert _strip_markdown("`code`") == "code"

    def test_preserves_plain_text(self):
        assert _strip_markdown("Hello world") == "Hello world"

    def test_multiline(self):
        md = "# Title\n\nSome **bold** text.\n- item"
        result = _strip_markdown(md)
        assert "Title" in result
        assert "bold" in result
        assert "**" not in result


def _mock_json_response(payload, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


def _mock_invalid_json_response(status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.side_effect = ValueError("not json")
    return resp


@pytest.mark.unit
class TestFetchMigrationConfig:
    @patch("PiFinder.ui.software.requests.get")
    def test_returns_dict_when_gate_open_and_url_set(self, mock_get):
        payload = {"nixos_for_everyone": True, "nixos_url": _NIXOS_URL}
        mock_get.return_value = _mock_json_response(payload)
        assert _fetch_migration_config() == payload

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_dict_when_gate_closed_but_url_set(self, mock_get):
        # Gate check is the caller's job; fetch only requires nixos_url.
        payload = {"nixos_for_everyone": False, "nixos_url": _NIXOS_URL}
        mock_get.return_value = _mock_json_response(payload)
        assert _fetch_migration_config() == payload

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_none_when_url_missing(self, mock_get):
        mock_get.return_value = _mock_json_response({"nixos_for_everyone": True})
        assert _fetch_migration_config() is None

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_none_when_url_empty(self, mock_get):
        mock_get.return_value = _mock_json_response(
            {"nixos_for_everyone": True, "nixos_url": ""}
        )
        assert _fetch_migration_config() is None

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_none_on_http_error(self, mock_get):
        mock_get.return_value = _mock_json_response(
            {"nixos_for_everyone": True, "nixos_url": _NIXOS_URL}, status_code=404
        )
        assert _fetch_migration_config() is None

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_none_on_connection_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError
        assert _fetch_migration_config() is None

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_none_on_timeout(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout
        assert _fetch_migration_config() is None

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_none_on_malformed_json(self, mock_get):
        mock_get.return_value = _mock_invalid_json_response()
        assert _fetch_migration_config() is None

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_none_when_payload_is_not_object(self, mock_get):
        mock_get.return_value = _mock_json_response(["nixos_for_everyone"])
        assert _fetch_migration_config() is None
