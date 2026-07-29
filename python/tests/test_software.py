from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

# Installs the _() gettext builtin the UI modules rely on; must precede ui imports.
import PiFinder.i18n  # noqa: F401
from PiFinder.ui.software import (
    UISoftware,
    UPDATE_MANIFEST_URL,
    _annotate_trunk_entries,
    _entry_detail,
    _entry_row_parts,
    _fetch_update_manifest,
    _format_age,
    _load_cached_manifest,
    _parse_manifest,
    _save_cached_manifest,
    _strip_markdown,
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


def _iso_ago(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


@pytest.mark.unit
class TestFormatAge:
    def test_minutes(self):
        assert _format_age(_iso_ago(minutes=5)) == "5m ago"

    def test_hours(self):
        assert _format_age(_iso_ago(hours=3, minutes=10)) == "3h ago"

    def test_days(self):
        assert _format_age(_iso_ago(days=2, hours=1)) == "2d ago"

    def test_future_timestamp_clamps_to_zero(self):
        assert _format_age(_iso_ago(minutes=-5)) == "0m ago"

    def test_none(self):
        assert _format_age(None) is None

    def test_garbage(self):
        assert _format_age("not-a-date") is None


@pytest.mark.unit
class TestEntryRowParts:
    def test_pr_row_leads_with_bare_number(self):
        prefix, text = _entry_row_parts(
            {
                "kind": "pr",
                "number": 534,
                "label": "PR#534-2692406",
                "title": "feat(catalog): add observable asteroids",
            }
        )
        assert prefix == "534 "
        assert text == "feat(catalog): add observable asteroids"

    def test_trunk_row_shows_branch_name(self):
        prefix, text = _entry_row_parts(
            {
                "kind": "trunk",
                "is_trunk": True,
                "label": "nixos-d1657e6",
                "source_ref": "nixos",
            }
        )
        assert prefix == "• "
        assert text == "nixos"

    def test_release_row_shows_label(self):
        prefix, text = _entry_row_parts(
            {"kind": "release", "label": "v3.0.0-beta", "title": "PiFinder v3.0.0-beta"}
        )
        assert prefix == ""
        assert text == "v3.0.0-beta"


@pytest.mark.unit
class TestEntryDetail:
    def test_unavailable_reason_wins_over_age(self):
        entry = {
            "unavailable": True,
            "subtitle": "Broken build (not in cache)",
            "built_at": _iso_ago(minutes=5),
        }
        assert _entry_detail(entry) == "Broken build (not in cache)"

    def test_build_age_and_short_hash_when_available(self):
        entry = {
            "subtitle": "Some title",
            "built_at": _iso_ago(minutes=12),
            "source_sha": "2692406bff684a56a2acce1febffb015aad72038",
        }
        assert _entry_detail(entry) == "built 12m ago · 2692406"

    def test_build_age_without_hash(self):
        entry = {"subtitle": "Some title", "built_at": _iso_ago(minutes=12)}
        assert _entry_detail(entry) == "built 12m ago"

    def test_hash_without_build_age(self):
        entry = {"subtitle": "Some title", "source_sha": "d1657e66b6ca4e14"}
        assert _entry_detail(entry) == "d1657e6"

    def test_falls_back_to_subtitle_without_build_info(self):
        assert _entry_detail({"subtitle": "Some title"}) == "Some title"


@pytest.mark.unit
class TestTrunkNixosMarker:
    def _manifest_with_trunk(self, **extra):
        trunk = {
            "kind": "trunk",
            "label": "main-abc1234",
            "title": "main branch",
            "version": "main-abc1234",
            "source_repo": "brickbots/PiFinder",
            "source_ref": "main",
            "store_path": "/nix/store/aaa-nixos-system-pifinder",
            "available": True,
        }
        trunk.update(extra)
        return {"schema": 1, "channels": {"unstable": [trunk]}}

    def test_parse_drops_trunk_marked_non_nixos(self):
        channels = _parse_manifest(self._manifest_with_trunk(nixos_branch=False))
        assert channels["unstable"] == []

    def test_parse_keeps_trunk_marked_nixos(self):
        channels = _parse_manifest(self._manifest_with_trunk(nixos_branch=True))
        assert channels["unstable"][0]["is_trunk"] is True

    def test_parse_keeps_unannotated_trunk(self):
        channels = _parse_manifest(self._manifest_with_trunk())
        assert len(channels["unstable"]) == 1

    @patch("PiFinder.ui.software.requests.head")
    def test_annotate_marks_nixos_branch(self, mock_head):
        mock_head.return_value = MagicMock(status_code=200)
        manifest = self._manifest_with_trunk()
        _annotate_trunk_entries(manifest)
        assert manifest["channels"]["unstable"][0]["nixos_branch"] is True
        url = mock_head.call_args[0][0]
        assert url == (
            "https://raw.githubusercontent.com/brickbots/PiFinder/main/flake.nix"
        )

    @patch("PiFinder.ui.software.requests.head")
    def test_annotate_marks_non_nixos_branch(self, mock_head):
        mock_head.return_value = MagicMock(status_code=404)
        manifest = self._manifest_with_trunk()
        _annotate_trunk_entries(manifest)
        assert manifest["channels"]["unstable"][0]["nixos_branch"] is False

    @patch("PiFinder.ui.software.requests.head")
    def test_annotate_leaves_entry_alone_on_network_error(self, mock_head):
        mock_head.side_effect = requests.exceptions.ConnectionError
        manifest = self._manifest_with_trunk()
        _annotate_trunk_entries(manifest)
        assert "nixos_branch" not in manifest["channels"]["unstable"][0]


@pytest.mark.unit
class TestManifestCache:
    def test_round_trip(self, tmp_path):
        manifest = {"schema": 1, "channels": {"stable": [], "beta": [], "unstable": []}}
        cache = tmp_path / "update_manifest.json"
        with patch("PiFinder.ui.software.MANIFEST_CACHE_PATH", cache):
            _save_cached_manifest(manifest)
            assert _load_cached_manifest() == manifest

    def test_missing_cache_returns_none(self, tmp_path):
        cache = tmp_path / "update_manifest.json"
        with patch("PiFinder.ui.software.MANIFEST_CACHE_PATH", cache):
            assert _load_cached_manifest() is None

    def test_wrong_schema_returns_none(self, tmp_path):
        cache = tmp_path / "update_manifest.json"
        cache.write_text('{"schema": 99}')
        with patch("PiFinder.ui.software.MANIFEST_CACHE_PATH", cache):
            assert _load_cached_manifest() is None

    def test_corrupt_cache_returns_none(self, tmp_path):
        cache = tmp_path / "update_manifest.json"
        cache.write_text("{nope")
        with patch("PiFinder.ui.software.MANIFEST_CACHE_PATH", cache):
            assert _load_cached_manifest() is None


@pytest.mark.unit
class TestManualRefresh:
    def _ui(self, phase):
        ui = UISoftware.__new__(UISoftware)
        ui._phase = phase
        ui._key_buffer = []
        ui._elipsis_count = 30
        return ui

    def test_square_refetches_in_browse(self):
        ui = self._ui("browse")
        with patch.object(UISoftware, "_start_refresh") as mock_start:
            ui.key_square()
        mock_start.assert_called_once()
        assert ui._phase == "browse"

    def test_square_retries_from_offline_via_loading(self):
        ui = self._ui("offline")
        with patch.object(UISoftware, "_start_refresh") as mock_start:
            ui.key_square()
        mock_start.assert_called_once()
        assert ui._phase == "loading"

    def test_square_does_not_refetch_in_confirm(self):
        ui = self._ui("confirm")
        with patch.object(UISoftware, "_start_refresh") as mock_start:
            ui.key_square()
        mock_start.assert_not_called()


@pytest.mark.unit
class TestListRollbackTargets:
    def _targets(self, value):
        ui = UISoftware.__new__(UISoftware)
        with patch("PiFinder.ui.software.sys_utils") as mock_sys:
            mock_sys.list_rollback_targets.return_value = value
            return ui._list_rollback_targets()

    def test_valid_entries_pass_through(self):
        entries = [{"label": "gen 42", "ref": "/nix/store/aaa"}]
        assert self._targets(entries) == entries

    def test_non_dict_and_unlabeled_entries_dropped(self):
        entries = [
            "garbage",
            {"ref": "/nix/store/aaa"},
            {"label": 7},
            {"label": "gen 42"},
        ]
        assert self._targets(entries) == [{"label": "gen 42"}]

    def test_non_iterable_result_yields_empty(self):
        assert self._targets(None) == []


@pytest.mark.unit
class TestConsumeRefreshResult:
    def _ui(self, phase):
        ui = UISoftware.__new__(UISoftware)
        ui._phase = phase
        ui._checking = True
        ui._check_failed = False
        ui._refresh_result = None
        return ui

    def test_success_moves_loading_to_browse(self):
        ui = self._ui("loading")
        ui._refresh_result = ("ok", {"stable": [], "beta": [], "unstable": []})
        with patch.object(UISoftware, "_apply_manifest") as mock_apply:
            ui._consume_refresh_result()
        assert ui._phase == "browse"
        assert ui._checking is False
        assert ui._check_failed is False
        mock_apply.assert_called_once()

    def test_failure_without_cache_or_rollback_goes_offline(self):
        ui = self._ui("loading")
        ui._refresh_result = ("error", None)
        with patch.object(UISoftware, "_list_rollback_targets", return_value=[]):
            ui._consume_refresh_result()
        assert ui._phase == "offline"
        assert ui._checking is False

    def test_failure_with_cached_list_only_flags(self):
        ui = self._ui("browse")
        ui._refresh_result = ("error", None)
        ui._consume_refresh_result()
        assert ui._phase == "browse"
        assert ui._check_failed is True

    def test_no_result_is_a_noop(self):
        ui = self._ui("browse")
        ui._consume_refresh_result()
        assert ui._checking is True
