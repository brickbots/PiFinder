import pytest
from unittest.mock import MagicMock, patch

from PiFinder.ui.software import (
    _fetch_update_manifest,
    _strip_markdown,
    UPDATE_MANIFEST_URL,
    UISoftware,
)


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


@pytest.mark.unit
def test_unstable_list_keeps_current_trunk_entry_visible():
    ui = UISoftware.__new__(UISoftware)
    ui._channel_names = ["unstable"]
    ui._channel_index = 0
    ui._software_version = "nixos-current"
    ui._channels = {
        "unstable": [
            {"label": "nixos-current", "version": "nixos-current", "is_trunk": True},
            {"label": "PR#1-abcdef0", "version": "PR#1-abcdef0"},
        ]
    }

    ui._refresh_version_list()

    assert [entry["label"] for entry in ui._version_list] == [
        "nixos-current",
        "PR#1-abcdef0",
    ]


@pytest.mark.unit
def test_stable_list_filters_current_version():
    ui = UISoftware.__new__(UISoftware)
    ui._channel_names = ["stable"]
    ui._channel_index = 0
    ui._software_version = "nixos-current"
    ui._channels = {
        "stable": [
            {"label": "nixos-current", "version": "nixos-current"},
            {"label": "nixos-next", "version": "nixos-next"},
        ]
    }

    ui._refresh_version_list()

    assert [entry["label"] for entry in ui._version_list] == ["nixos-next"]


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
