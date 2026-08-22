import json
import os

import pytest

from PiFinder import utils


def _write_build(tmp_path, monkeypatch, **fields):
    f = tmp_path / "current-build.json"
    f.write_text(json.dumps(fields))
    monkeypatch.setattr(utils, "current_build_json", f)
    return f


def _fake_running(monkeypatch, store_path):
    """Pretend the booted system resolves to store_path (None = off-device)."""
    monkeypatch.setattr(utils, "running_system_store_path", lambda: store_path)


@pytest.mark.unit
class TestGetVersion:
    def test_missing_file_is_unknown(self, tmp_path, monkeypatch):
        monkeypatch.setattr(utils, "current_build_json", tmp_path / "nope.json")
        assert utils.get_version() == "Unknown"

    def test_label_returned_when_build_is_running(self, tmp_path, monkeypatch):
        store = "/nix/store/abc12345-nixos-system-pifinder"
        _write_build(tmp_path, monkeypatch, store_path=store, version="PR362-005abc")
        _fake_running(monkeypatch, store)
        assert utils.get_version() == "PR362-005abc"

    def test_off_device_trusts_the_label(self, tmp_path, monkeypatch):
        # No /run/current-system to compare against — don't cry stale.
        _write_build(
            tmp_path, monkeypatch, store_path="/nix/store/x-nixos-system", version="v1"
        )
        _fake_running(monkeypatch, None)
        assert utils.get_version() == "v1"

    def test_stale_label_falls_back_to_running_hash(self, tmp_path, monkeypatch):
        # current-build.json names the selected build; the device booted another.
        _write_build(
            tmp_path,
            monkeypatch,
            store_path="/nix/store/selected00-nixos-system-pifinder",
            version="PR362-005abc",
        )
        _fake_running(monkeypatch, "/nix/store/running99-nixos-system-pifinder")
        # Never assert the label the device isn't running; report the real build.
        assert utils.get_version() == "running9"

    def test_stale_and_no_running_path_is_unknown(self, tmp_path, monkeypatch):
        _write_build(
            tmp_path,
            monkeypatch,
            store_path="/nix/store/selected00-nixos-system",
            version="PR362-005abc",
        )
        # build_is_running -> False (mismatch), running unknown -> Unknown, not a lie.
        monkeypatch.setattr(utils, "build_is_running", lambda p: False)
        _fake_running(monkeypatch, None)
        assert utils.get_version() == "Unknown"


@pytest.mark.unit
class TestBuildIsRunning:
    def test_direct_match(self, monkeypatch):
        store = "/nix/store/base00-nixos-system-pifinder"
        _fake_running(monkeypatch, store)
        assert utils.build_is_running(store) is True

    def test_mismatch(self, monkeypatch):
        _fake_running(monkeypatch, "/nix/store/other-nixos-system")
        assert utils.build_is_running("/nix/store/base00-nixos-system") is False

    def test_none_running_assumes_match(self, monkeypatch):
        _fake_running(monkeypatch, None)
        assert utils.build_is_running("/nix/store/base00-nixos-system") is True

    def test_empty_store_path_is_false(self, monkeypatch):
        _fake_running(monkeypatch, "/nix/store/x")
        assert utils.build_is_running("") is False
        assert utils.build_is_running(None) is False

    def test_running_camera_specialisation_matches_base(self, tmp_path, monkeypatch):
        # The device boots <base>/specialisation/<cam>, a distinct store path;
        # the recorded base must still count as running.
        base = tmp_path / "base-nixos-system"
        spec_target = tmp_path / "specialised00-nixos-system"
        spec_target.mkdir()
        (base / "specialisation").mkdir(parents=True)
        os.symlink(spec_target, base / "specialisation" / "imx462")
        _fake_running(monkeypatch, os.path.realpath(spec_target))
        assert utils.build_is_running(str(base)) is True


@pytest.mark.unit
class TestRunningSystemStorePath:
    def test_none_when_not_a_symlink(self, tmp_path, monkeypatch):
        monkeypatch.setattr(utils, "running_system_link", tmp_path / "absent")
        assert utils.running_system_store_path() is None

    def test_none_when_not_a_store_path(self, tmp_path, monkeypatch):
        target = tmp_path / "somewhere"
        target.mkdir()
        link = tmp_path / "current-system"
        os.symlink(target, link)
        monkeypatch.setattr(utils, "running_system_link", link)
        assert utils.running_system_store_path() is None
