"""Unit tests for the rollback notice that the boot watchdog leaves."""

import json

import pytest

from PiFinder.main import rollback_cause


@pytest.mark.unit
@pytest.mark.parametrize(
    "content, cause",
    [
        ({"failed": "/nix/store/a", "by": "recovery"}, "recovery"),
        ({"failed": "/nix/store/a", "by": "trial"}, "trial"),
        ({"failed": "/nix/store/a"}, ""),
        ({"by": 7}, ""),
        ([], ""),
    ],
)
def test_rollback_cause(tmp_path, content, cause):
    notice = tmp_path / "upgrade_failed.json"
    notice.write_text(json.dumps(content))
    assert rollback_cause(notice) == cause


@pytest.mark.unit
def test_rollback_cause_of_a_broken_notice(tmp_path):
    notice = tmp_path / "upgrade_failed.json"
    notice.write_text("{not json")
    assert rollback_cause(notice) == ""
    assert rollback_cause(tmp_path / "missing.json") == ""
