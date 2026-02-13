import pytest
from unittest.mock import patch, MagicMock

from PiFinder.ui.software import (
    update_needed,
    _parse_version,
    _strip_markdown,
    _meets_min_version,
    _version_from_tag,
    _fetch_github_releases,
    _fetch_testable_prs,
    _fetch_build_json,
    GITHUB_REPO,
    GITHUB_RAW_URL,
)


# ---------------------------------------------------------------------------
# Version parsing
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseVersion:
    def test_simple_version(self):
        assert _parse_version("2.4.0") == (2, 4, 0, 1, "")

    def test_prerelease_version(self):
        result = _parse_version("2.5.0-beta.1")
        assert result == (2, 5, 0, 0, "beta.1")

    def test_prerelease_sorts_below_release(self):
        assert _parse_version("2.5.0-beta.1") < _parse_version("2.5.0")

    def test_whitespace_stripped(self):
        assert _parse_version("  2.4.0\n") == (2, 4, 0, 1, "")


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

    def test_prerelease_to_release(self):
        assert update_needed("2.5.0-beta.1", "2.5.0") is True

    def test_release_to_prerelease_same(self):
        assert update_needed("2.5.0", "2.5.0-beta.1") is False

    def test_prerelease_higher_minor(self):
        assert update_needed("2.4.0", "2.5.0-beta.1") is True

    def test_garbage_input_returns_false(self):
        assert update_needed("garbage", "2.4.0") is False

    def test_empty_string_returns_false(self):
        assert update_needed("", "") is False

    def test_partial_version_returns_false(self):
        assert update_needed("2.4", "2.5.0") is False

    def test_unknown_returns_false(self):
        assert update_needed("2.4.0", "Unknown") is False


# ---------------------------------------------------------------------------
# Markdown stripping
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Min version cutoff
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMeetsMinVersion:
    def test_exact_min_version(self):
        assert _meets_min_version("2.5.0") is True

    def test_above_min_version(self):
        assert _meets_min_version("2.6.0") is True

    def test_below_min_version(self):
        assert _meets_min_version("2.4.0") is False

    def test_prerelease_at_min(self):
        # 2.5.0-beta.1 < 2.5.0, so below minimum
        assert _meets_min_version("2.5.0-beta.1") is False

    def test_prerelease_above_min(self):
        assert _meets_min_version("2.6.0-beta.1") is True

    def test_garbage_returns_false(self):
        assert _meets_min_version("garbage") is False

    def test_old_major_version(self):
        assert _meets_min_version("1.0.0") is False


@pytest.mark.unit
class TestVersionFromTag:
    def test_strips_v_prefix(self):
        assert _version_from_tag("v2.5.0") == "2.5.0"

    def test_no_prefix(self):
        assert _version_from_tag("2.5.0") == "2.5.0"

    def test_prerelease_tag(self):
        assert _version_from_tag("v2.6.0-beta.1") == "2.6.0-beta.1"


# ---------------------------------------------------------------------------
# Build JSON fetching
# ---------------------------------------------------------------------------

MOCK_BUILD_JSON = {"store_path": "/nix/store/abc123-nixos-system-pifinder", "version": "2.6.0"}


@pytest.mark.unit
class TestFetchBuildJson:
    @patch("PiFinder.ui.software.requests.get")
    def test_returns_data_on_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_BUILD_JSON
        mock_get.return_value = mock_resp

        result = _fetch_build_json("v2.6.0")

        assert result == MOCK_BUILD_JSON
        mock_get.assert_called_once_with(
            f"{GITHUB_RAW_URL}/v2.6.0/pifinder-build.json",
            timeout=10,
        )

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_none_on_404(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        assert _fetch_build_json("v1.0.0") is None

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_none_on_missing_store_path(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"version": "2.6.0"}
        mock_get.return_value = mock_resp

        assert _fetch_build_json("v2.6.0") is None

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_none_on_network_error(self, mock_get):
        import requests as req

        mock_get.side_effect = req.exceptions.ConnectionError("no network")

        assert _fetch_build_json("v2.6.0") is None


# ---------------------------------------------------------------------------
# GitHub releases API parsing
# ---------------------------------------------------------------------------

MOCK_RELEASES = [
    {
        "tag_name": "v2.6.0",
        "prerelease": False,
        "draft": False,
        "body": "## v2.6.0\n- Feature A",
    },
    {
        "tag_name": "v2.5.1",
        "prerelease": False,
        "draft": False,
        "body": "Bugfix release",
    },
    {
        "tag_name": "v2.6.0-beta.1",
        "prerelease": True,
        "draft": False,
        "body": "Beta changelog",
    },
    {
        "tag_name": "v2.5.0-beta.2",
        "prerelease": True,
        "draft": False,
        "body": "Old beta",
    },
    {
        "tag_name": "v2.4.0",
        "prerelease": False,
        "draft": False,
        "body": "Pre-NixOS release",
    },
    {
        "tag_name": "v2.3.0",
        "prerelease": False,
        "draft": True,
        "body": "Draft release",
    },
]

BUILD_JSONS = {
    "v2.6.0": {"store_path": "/nix/store/aaa-nixos-system-pifinder", "version": "2.6.0"},
    "v2.5.1": {"store_path": "/nix/store/bbb-nixos-system-pifinder", "version": "2.5.1"},
    "v2.6.0-beta.1": {"store_path": "/nix/store/ccc-nixos-system-pifinder", "version": "2.6.0-beta.1"},
}


def _make_build_json_mock(build_jsons):
    """Create a _fetch_build_json mock that returns data from a dict."""

    def _mock(ref):
        return build_jsons.get(ref)

    return _mock


@pytest.mark.unit
class TestFetchGitHubReleases:
    @patch("PiFinder.ui.software._fetch_build_json")
    @patch("PiFinder.ui.software.requests.get")
    def test_partitions_stable_and_beta(self, mock_get, mock_build):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_RELEASES
        mock_get.return_value = mock_resp
        mock_build.side_effect = _make_build_json_mock(BUILD_JSONS)

        stable, beta = _fetch_github_releases()

        stable_versions = [e["version"] for e in stable]
        beta_versions = [e["version"] for e in beta]

        assert "2.6.0" in stable_versions
        assert "2.5.1" in stable_versions
        assert "2.6.0-beta.1" in beta_versions

    @patch("PiFinder.ui.software._fetch_build_json")
    @patch("PiFinder.ui.software.requests.get")
    def test_filters_below_min_version(self, mock_get, mock_build):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_RELEASES
        mock_get.return_value = mock_resp
        mock_build.side_effect = _make_build_json_mock(BUILD_JSONS)

        stable, beta = _fetch_github_releases()

        all_versions = [e["version"] for e in stable + beta]
        assert "2.4.0" not in all_versions

    @patch("PiFinder.ui.software._fetch_build_json")
    @patch("PiFinder.ui.software.requests.get")
    def test_excludes_drafts(self, mock_get, mock_build):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_RELEASES
        mock_get.return_value = mock_resp
        mock_build.side_effect = _make_build_json_mock(BUILD_JSONS)

        stable, beta = _fetch_github_releases()

        all_labels = [e["label"] for e in stable + beta]
        assert "v2.3.0" not in all_labels

    @patch("PiFinder.ui.software._fetch_build_json")
    @patch("PiFinder.ui.software.requests.get")
    def test_ref_is_store_path(self, mock_get, mock_build):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [MOCK_RELEASES[0]]
        mock_get.return_value = mock_resp
        mock_build.return_value = BUILD_JSONS["v2.6.0"]

        stable, _ = _fetch_github_releases()

        assert stable[0]["ref"] == "/nix/store/aaa-nixos-system-pifinder"

    @patch("PiFinder.ui.software._fetch_build_json")
    @patch("PiFinder.ui.software.requests.get")
    def test_preserves_changelog_body(self, mock_get, mock_build):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [MOCK_RELEASES[0]]
        mock_get.return_value = mock_resp
        mock_build.return_value = BUILD_JSONS["v2.6.0"]

        stable, _ = _fetch_github_releases()

        assert stable[0]["notes"] == "## v2.6.0\n- Feature A"

    @patch("PiFinder.ui.software.requests.get")
    def test_api_failure_returns_empty(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_get.return_value = mock_resp

        stable, beta = _fetch_github_releases()

        assert stable == []
        assert beta == []

    @patch("PiFinder.ui.software.requests.get")
    def test_network_error_returns_empty(self, mock_get):
        import requests as req

        mock_get.side_effect = req.exceptions.ConnectionError("no network")

        stable, beta = _fetch_github_releases()

        assert stable == []
        assert beta == []

    @patch("PiFinder.ui.software._fetch_build_json")
    @patch("PiFinder.ui.software.requests.get")
    def test_prerelease_at_min_filtered(self, mock_get, mock_build):
        """2.5.0-beta.2 is below 2.5.0 minimum, should be excluded."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_RELEASES
        mock_get.return_value = mock_resp
        mock_build.side_effect = _make_build_json_mock(BUILD_JSONS)

        _, beta = _fetch_github_releases()

        beta_versions = [e["version"] for e in beta]
        assert "2.5.0-beta.2" not in beta_versions

    @patch("PiFinder.ui.software._fetch_build_json")
    @patch("PiFinder.ui.software.requests.get")
    def test_skips_entries_without_build_json(self, mock_get, mock_build):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [MOCK_RELEASES[0]]
        mock_get.return_value = mock_resp
        mock_build.return_value = None

        stable, beta = _fetch_github_releases()

        assert stable == []
        assert beta == []


# ---------------------------------------------------------------------------
# Testable PRs
# ---------------------------------------------------------------------------

MOCK_PRS = [
    {
        "number": 42,
        "title": "Fix star matching algorithm",
        "head": {"sha": "abc123def456"},
        "user": {"login": "contributor1"},
        "body": "This PR fixes the star matching.",
        "labels": [{"name": "testable"}],
    },
    {
        "number": 99,
        "title": "Add dark mode support",
        "head": {"sha": "789xyz000111"},
        "user": {"login": "contributor2"},
        "body": None,
        "labels": [{"name": "testable"}],
    },
]

PR_BUILD_JSONS = {
    "abc123def456": {"store_path": "/nix/store/pr42-nixos-system-pifinder", "version": "2.6.0-dev"},
    "789xyz000111": {"store_path": "/nix/store/pr99-nixos-system-pifinder", "version": "2.6.0-dev"},
}


@pytest.mark.unit
class TestFetchTestablePRs:
    @patch("PiFinder.ui.software._fetch_build_json")
    @patch("PiFinder.ui.software.requests.get")
    def test_builds_pr_entries(self, mock_get, mock_build):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_PRS
        mock_get.return_value = mock_resp
        mock_build.side_effect = _make_build_json_mock(PR_BUILD_JSONS)

        entries = _fetch_testable_prs()

        assert len(entries) == 2
        assert entries[0]["label"].startswith("PR#42")
        assert entries[1]["label"].startswith("PR#99")

    @patch("PiFinder.ui.software._fetch_build_json")
    @patch("PiFinder.ui.software.requests.get")
    def test_pr_ref_is_store_path(self, mock_get, mock_build):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [MOCK_PRS[0]]
        mock_get.return_value = mock_resp
        mock_build.return_value = PR_BUILD_JSONS["abc123def456"]

        entries = _fetch_testable_prs()

        assert entries[0]["ref"] == "/nix/store/pr42-nixos-system-pifinder"

    @patch("PiFinder.ui.software._fetch_build_json")
    @patch("PiFinder.ui.software.requests.get")
    def test_pr_version_from_build_json(self, mock_get, mock_build):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [MOCK_PRS[0]]
        mock_get.return_value = mock_resp
        mock_build.return_value = PR_BUILD_JSONS["abc123def456"]

        entries = _fetch_testable_prs()

        assert entries[0]["version"] == "2.6.0-dev"

    @patch("PiFinder.ui.software._fetch_build_json")
    @patch("PiFinder.ui.software.requests.get")
    def test_pr_notes_from_body(self, mock_get, mock_build):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_PRS
        mock_get.return_value = mock_resp
        mock_build.side_effect = _make_build_json_mock(PR_BUILD_JSONS)

        entries = _fetch_testable_prs()

        assert entries[0]["notes"] == "This PR fixes the star matching."
        assert entries[1]["notes"] is None

    @patch("PiFinder.ui.software.requests.get")
    def test_api_failure_returns_empty(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_get.return_value = mock_resp

        entries = _fetch_testable_prs()

        assert entries == []

    @patch("PiFinder.ui.software._fetch_build_json")
    @patch("PiFinder.ui.software.requests.get")
    def test_long_title_truncated(self, mock_get, mock_build):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "number": 7,
                "title": "A very long PR title that exceeds twenty characters",
                "head": {"sha": "aaa"},
                "user": {"login": "x"},
                "body": None,
                "labels": [{"name": "testable"}],
            }
        ]
        mock_get.return_value = mock_resp
        mock_build.return_value = {"store_path": "/nix/store/pr7-nixos", "version": "2.6.0-dev"}

        entries = _fetch_testable_prs()

        assert "..." in entries[0]["label"]
        assert entries[0]["label"].startswith("PR#7 ")

    @patch("PiFinder.ui.software._fetch_build_json")
    @patch("PiFinder.ui.software.requests.get")
    def test_skips_prs_without_build_json(self, mock_get, mock_build):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_PRS
        mock_get.return_value = mock_resp
        mock_build.return_value = None

        entries = _fetch_testable_prs()

        assert entries == []
