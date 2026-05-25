from unittest.mock import patch, MagicMock

import pytest
import requests

from PiFinder.ui.software import (
    update_needed,
    _strip_markdown,
    _fetch_migration_gate,
    _UNLOCK_SEQUENCE,
)


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


def _mock_response(text, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


@pytest.mark.unit
class TestFetchMigrationGate:
    @patch("PiFinder.ui.software.requests.get")
    def test_returns_true_when_gate_is_1(self, mock_get):
        mock_get.return_value = _mock_response("1")
        assert _fetch_migration_gate() is True

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_true_when_gate_is_1_with_whitespace(self, mock_get):
        mock_get.return_value = _mock_response("1\n")
        assert _fetch_migration_gate() is True

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_false_when_gate_is_0(self, mock_get):
        mock_get.return_value = _mock_response("0")
        assert _fetch_migration_gate() is False

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_false_when_empty(self, mock_get):
        mock_get.return_value = _mock_response("")
        assert _fetch_migration_gate() is False

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_false_on_http_error(self, mock_get):
        mock_get.return_value = _mock_response("1", status_code=404)
        assert _fetch_migration_gate() is False

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_false_on_connection_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError
        assert _fetch_migration_gate() is False

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_false_on_timeout(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout
        assert _fetch_migration_gate() is False

    @patch("PiFinder.ui.software.requests.get")
    def test_returns_false_for_arbitrary_text(self, mock_get):
        mock_get.return_value = _mock_response("yes")
        assert _fetch_migration_gate() is False
