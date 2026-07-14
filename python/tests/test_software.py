from unittest.mock import MagicMock, patch

import pytest
import requests

from PiFinder.ui.software import (
    UISoftware,
    UPDATE_MANIFEST_URL,
    _fetch_migration_config,
    _fetch_update_manifest,
    _migration_version_info_from_manifest,
    _strip_markdown,
    _UNLOCK_SEQUENCE,
    update_needed,
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


@pytest.mark.unit
class TestFetchUpdateManifest:
    @patch("PiFinder.ui.software.requests.get")
    def test_parses_manifest_channels(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "schema": 1,
            "channels": {
                "stable": [
                    {
                        "kind": "release",
                        "label": "v3.1.0",
                        "title": "PiFinder v3.1.0",
                        "version": "3.1.0",
                        "store_path": "/nix/store/aaa-nixos-system-pifinder",
                        "available": True,
                    }
                ],
                "beta": [],
                "unstable": [
                    {
                        "kind": "trunk",
                        "label": "nixos-abc1234",
                        "title": "nixos branch",
                        "version": "nixos-abc1234",
                        "store_path": "/nix/store/bbb-nixos-system-pifinder",
                        "available": True,
                    },
                    {
                        "kind": "pr",
                        "label": "PR#42-def5678",
                        "title": "Fix star matching algorithm",
                        "version": "PR#42-def5678",
                        "store_path": "/nix/store/ccc-nixos-system-pifinder",
                        "available": True,
                    },
                ],
            },
        }
        mock_get.return_value = mock_resp

        channels = _fetch_update_manifest()

        assert channels["stable"][0]["ref"] == "/nix/store/aaa-nixos-system-pifinder"
        assert channels["stable"][0]["channel"] == "stable"
        assert channels["unstable"][0]["is_trunk"] is True
        assert channels["unstable"][1]["label"] == "PR#42-def5678"
        mock_get.assert_called_once_with(UPDATE_MANIFEST_URL, timeout=10)

    @patch("PiFinder.ui.software.requests.get")
    def test_unavailable_manifest_entry_has_no_ref(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "schema": 1,
            "channels": {
                "stable": [],
                "beta": [],
                "unstable": [
                    {
                        "kind": "trunk",
                        "label": "main",
                        "title": "main branch",
                        "version": "main",
                        "store_path": None,
                        "available": False,
                        "reason": "no build",
                    }
                ],
            },
        }
        mock_get.return_value = mock_resp

        channels = _fetch_update_manifest()

        entry = channels["unstable"][0]
        assert entry["ref"] is None
        assert entry["unavailable"] is True
        assert entry["subtitle"] == "main branch (no build)"

    @patch("PiFinder.ui.software.requests.get")
    def test_invalid_store_path_is_unavailable(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "schema": 1,
            "channels": {
                "stable": [],
                "beta": [],
                "unstable": [
                    {
                        "kind": "pr",
                        "label": "PR#42-abcdef0",
                        "title": "Bad build",
                        "version": "PR#42-abcdef0",
                        "store_path": "not-a-store-path",
                        "available": True,
                    }
                ],
            },
        }
        mock_get.return_value = mock_resp

        channels = _fetch_update_manifest()

        entry = channels["unstable"][0]
        assert entry["ref"] is None
        assert entry["unavailable"] is True
        assert entry["subtitle"] == "Bad build (invalid build)"

    @patch("PiFinder.ui.software.requests.get")
    def test_rejects_unknown_schema(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"schema": 99, "channels": {}}
        mock_get.return_value = mock_resp

        with pytest.raises(ValueError):
            _fetch_update_manifest()


def _migration_entry(version="3.0.0", available=True, with_urls=True):
    # Mirror the real manifest: a migration-capable release carries both a
    # valid store_path (so available/unavailable resolves from it) and the
    # migration tarball URLs.
    entry = {
        "kind": "release",
        "label": f"v{version}",
        "version": version,
        "available": available,
        "store_path": (
            f"/nix/store/{'a' * 32}-nixos-system-pifinder-{version}"
            if available
            else None
        ),
    }
    if with_urls:
        base = f"https://example.invalid/releases/download/v{version}"
        entry["migration_url"] = f"{base}/pifinder-migration-v{version}.tar.zst"
        entry["migration_sha256_url"] = (
            f"{base}/pifinder-migration-v{version}.tar.zst.sha256"
        )
    return entry


def _manifest(stable=None, beta=None, unstable=None):
    return {
        "schema": 1,
        "channels": {
            "stable": stable or [],
            "beta": beta or [],
            "unstable": unstable or [],
        },
    }


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


@pytest.mark.unit
def test_unstable_list_hides_exact_running_build():
    # The running build is hidden from unstable by store-path identity; a
    # rebuilt PR (same number, new store path) is a real upgrade and stays.
    ui = UISoftware.__new__(UISoftware)
    ui._channel_names = ["unstable"]
    ui._channel_index = 0
    ui._software_version = "PR#1-abcdef0"
    ui._channels = {
        "unstable": [
            {
                "label": "nixos-trunk",
                "version": "nixos-trunk",
                "is_trunk": True,
                "ref": "/nix/store/bbb-trunk",
            },
            {
                "label": "PR#1-abcdef0",
                "version": "PR#1-abcdef0",
                "ref": "/nix/store/aaa-running",
            },
        ]
    }

    with patch(
        "PiFinder.ui.software._current_store_path",
        return_value="/nix/store/aaa-running",
    ):
        ui._refresh_version_list()

    assert [entry["label"] for entry in ui._version_list] == ["nixos-trunk"]


@pytest.mark.unit
def test_stable_list_filters_current_build_by_store_path():
    ui = UISoftware.__new__(UISoftware)
    ui._channel_names = ["stable"]
    ui._channel_index = 0
    ui._software_version = "3.0.0"
    ui._channels = {
        "stable": [
            {"label": "v3.0.0", "version": "3.0.0", "ref": "/nix/store/aaa-current"},
            {"label": "v3.1.0", "version": "3.1.0", "ref": "/nix/store/bbb-next"},
        ]
    }

    with patch(
        "PiFinder.ui.software._current_store_path",
        return_value="/nix/store/aaa-current",
    ):
        ui._refresh_version_list()

    assert [entry["label"] for entry in ui._version_list] == ["v3.1.0"]


@pytest.mark.unit
def test_recut_release_with_same_version_stays_visible():
    # A re-cut release reuses its version/label but is a different store path
    # — it must be offered as an upgrade, not hidden by a version-string match.
    ui = UISoftware.__new__(UISoftware)
    ui._channel_names = ["beta"]
    ui._channel_index = 0
    ui._software_version = "3.0.0"
    ui._channels = {
        "beta": [
            {"label": "v3.0.0-beta", "version": "3.0.0", "ref": "/nix/store/bbb-recut"},
        ]
    }

    with patch(
        "PiFinder.ui.software._current_store_path",
        return_value="/nix/store/aaa-old-build",
    ):
        ui._refresh_version_list()

    assert [entry["label"] for entry in ui._version_list] == ["v3.0.0-beta"]


@pytest.mark.unit
def test_unknown_current_build_hides_nothing():
    ui = UISoftware.__new__(UISoftware)
    ui._channel_names = ["stable"]
    ui._channel_index = 0
    ui._software_version = "3.0.0"
    ui._channels = {
        "stable": [
            {"label": "v3.0.0", "version": "3.0.0", "ref": "/nix/store/aaa"},
        ]
    }

    with patch("PiFinder.ui.software._current_store_path", return_value=None):
        ui._refresh_version_list()

    assert [entry["label"] for entry in ui._version_list] == ["v3.0.0"]


@pytest.mark.unit
def test_unavailable_version_has_no_install_option():
    ui = UISoftware.__new__(UISoftware)
    ui._phase = "browse"
    ui._focus = "list"
    ui._list_index = 0
    ui._version_list = [
        {
            "label": "main",
            "version": "main",
            "subtitle": "main branch (no build)",
            "unavailable": True,
        }
    ]

    ui.key_right()

    assert ui._phase == "confirm"
    assert ui._confirm_options == ["Cancel"]
