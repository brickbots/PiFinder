from unittest.mock import patch, MagicMock

import pytest
import requests

from PiFinder.ui.software import (
    update_needed,
    _strip_markdown,
    _fetch_migration_config,
    _fetch_update_manifest,
    _migration_version_info_from_manifest,
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
    def test_returns_dict_when_gate_closed(self, mock_get):
        # Gate check is the caller's job; fetch just parses the JSON.
        payload = {"nixos_for_everyone": False}
        mock_get.return_value = _mock_json_response(payload)
        assert _fetch_migration_config() == payload

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_dict_without_url(self, mock_get):
        # The tarball comes from the manifest now, so the gate no longer needs a
        # nixos_url — only the nixos_for_everyone flag matters to the caller.
        payload = {"nixos_for_everyone": True}
        mock_get.return_value = _mock_json_response(payload)
        assert _fetch_migration_config() == payload

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


def _migration_entry(version="3.0.0", available=True, with_urls=True):
    entry = {"version": version, "available": available}
    if with_urls:
        base = f"https://example.invalid/releases/download/v{version}"
        entry["migration_url"] = f"{base}/pifinder-migration-v{version}.tar.zst"
        entry["migration_sha256_url"] = (
            f"{base}/pifinder-migration-v{version}.tar.zst.sha256"
        )
    return entry


def _manifest(stable=None, beta=None, unstable=None):
    return {
        "channels": {
            "stable": stable or [],
            "beta": beta or [],
            "unstable": unstable or [],
        }
    }


@pytest.mark.unit
class TestFetchUpdateManifest:
    @patch("PiFinder.ui.software.requests.get")
    def test_returns_dict(self, mock_get):
        payload = {"channels": {}}
        mock_get.return_value = _mock_json_response(payload)
        assert _fetch_update_manifest() == payload

    @patch("PiFinder.ui.software.requests.get")
    def test_none_on_http_error(self, mock_get):
        mock_get.return_value = _mock_json_response({}, status_code=500)
        assert _fetch_update_manifest() is None

    @patch("PiFinder.ui.software.requests.get")
    def test_none_on_malformed_json(self, mock_get):
        mock_get.return_value = _mock_invalid_json_response()
        assert _fetch_update_manifest() is None


def _mock_head_response(size_bytes=None, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {} if size_bytes is None else {"Content-Length": str(size_bytes)}
    return resp


# Selection also HEADs the chosen tarball for its size, so requests.head is
# stubbed throughout (never hit the network from tests).
@pytest.mark.unit
@patch(
    "PiFinder.ui.software.requests.head",
    side_effect=requests.exceptions.ConnectionError,
)
class TestMigrationVersionInfoFromManifest:
    @patch("PiFinder.ui.software.requests.get")
    def test_prefers_stable(self, mock_get, _mock_head):
        mock_get.return_value = _mock_json_response(
            _manifest(
                stable=[_migration_entry("3.0.0")],
                beta=[_migration_entry("3.1.0-beta")],
                unstable=[_migration_entry("nixos-abc")],
            )
        )
        info = _migration_version_info_from_manifest()
        assert info["version"] == "3.0.0"
        assert info["type"] == "upgrade"
        assert info["migration_url"].endswith("pifinder-migration-v3.0.0.tar.zst")
        assert info["migration_sha256_url"].endswith(".sha256")

    @patch("PiFinder.ui.software.requests.get")
    def test_includes_size_when_head_succeeds(self, mock_get, mock_head):
        mock_get.return_value = _mock_json_response(
            _manifest(stable=[_migration_entry("3.0.0")])
        )
        mock_head.side_effect = None
        mock_head.return_value = _mock_head_response(size_bytes=300 * 1024 * 1024)
        info = _migration_version_info_from_manifest()
        assert info["migration_size_mb"] == 300

    @patch("PiFinder.ui.software.requests.get")
    def test_omits_size_when_head_fails(self, mock_get, _mock_head):
        mock_get.return_value = _mock_json_response(
            _manifest(stable=[_migration_entry("3.0.0")])
        )
        info = _migration_version_info_from_manifest()
        assert "migration_size_mb" not in info

    @patch("PiFinder.ui.software.requests.get")
    def test_falls_back_to_beta_when_stable_empty(self, mock_get, _mock_head):
        mock_get.return_value = _mock_json_response(
            _manifest(beta=[_migration_entry("3.1.0-beta")])
        )
        assert _migration_version_info_from_manifest()["version"] == "3.1.0-beta"

    @patch("PiFinder.ui.software.requests.get")
    def test_falls_back_to_unstable_last(self, mock_get, _mock_head):
        mock_get.return_value = _mock_json_response(
            _manifest(unstable=[_migration_entry("nixos-abc")])
        )
        assert _migration_version_info_from_manifest()["version"] == "nixos-abc"

    @patch("PiFinder.ui.software.requests.get")
    def test_skips_unavailable_entries(self, mock_get, _mock_head):
        mock_get.return_value = _mock_json_response(
            _manifest(
                stable=[_migration_entry("3.0.0", available=False)],
                beta=[_migration_entry("3.1.0-beta")],
            )
        )
        assert _migration_version_info_from_manifest()["version"] == "3.1.0-beta"

    @patch("PiFinder.ui.software.requests.get")
    def test_skips_entries_without_migration_tarball(self, mock_get, _mock_head):
        mock_get.return_value = _mock_json_response(
            _manifest(
                stable=[_migration_entry("3.0.0", with_urls=False)],
                beta=[_migration_entry("3.1.0-beta")],
            )
        )
        assert _migration_version_info_from_manifest()["version"] == "3.1.0-beta"

    @patch("PiFinder.ui.software.requests.get")
    def test_none_when_no_migration_entries(self, mock_get, _mock_head):
        mock_get.return_value = _mock_json_response(_manifest())
        assert _migration_version_info_from_manifest() is None

    @patch("PiFinder.ui.software.requests.get")
    def test_none_on_network_error(self, mock_get, _mock_head):
        mock_get.side_effect = requests.exceptions.ConnectionError
        assert _migration_version_info_from_manifest() is None

    @patch("PiFinder.ui.software.requests.get")
    def test_none_when_channels_missing(self, mock_get, _mock_head):
        mock_get.return_value = _mock_json_response({"schema": 1})
        assert _migration_version_info_from_manifest() is None
