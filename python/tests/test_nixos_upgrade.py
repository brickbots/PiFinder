import json

import pytest

from PiFinder import nixos_upgrade


STORE = "/nix/store/abc123-nixos-system-pifinder"


@pytest.mark.unit
def test_valid_store_path_rejects_non_store_refs():
    assert nixos_upgrade.valid_store_path(STORE)
    assert not nixos_upgrade.valid_store_path("release")
    assert not nixos_upgrade.valid_store_path("/tmp/not-a-store-path")


@pytest.mark.unit
def test_parse_progress_event_ignores_malformed_lines():
    assert nixos_upgrade.parse_progress_event("copying path") is None
    assert nixos_upgrade.parse_progress_event("@nix {") is None


@pytest.mark.unit
def test_parse_progress_event_extracts_copy_path():
    line = (
        '@nix {"action":"start","id":7,"type":100,'
        f'"text":"copying path \'{STORE}\' from cache"}}'
    )
    event = nixos_upgrade.parse_progress_event(line)

    assert event == nixos_upgrade.ProgressEvent("start", 7, 100, STORE)


@pytest.mark.unit
def test_run_build_uses_no_link(monkeypatch, tmp_path):
    started = {}

    class FakeStdout:
        def __iter__(self):
            return iter(())

    class FakeProcess:
        stdout = FakeStdout()

        def wait(self):
            return 0

    def fake_popen(args, **kwargs):
        started["args"] = args
        return FakeProcess()

    monkeypatch.setattr(nixos_upgrade.subprocess, "Popen", fake_popen)

    rc = nixos_upgrade.run_build(
        STORE,
        nixos_upgrade.DownloadEstimate({}, ()),
        status_file=tmp_path / "status",
        log_file=tmp_path / "log",
    )

    assert rc == 0
    assert "--no-link" in started["args"]


@pytest.mark.unit
def test_estimate_download_uses_per_path_sizes(monkeypatch):
    dry = f"these paths will be fetched:\n  {STORE}\n"

    def fake_command(args, **kwargs):
        class Result:
            returncode = 0
            stderr = dry
            stdout = json.dumps([{"path": STORE, "downloadSize": 1024}])

        return Result()

    monkeypatch.setattr(nixos_upgrade, "command", fake_command)
    monkeypatch.setattr(nixos_upgrade, "path_exists", lambda _path: False)

    estimate = nixos_upgrade.estimate_download(STORE)

    assert estimate.paths == (STORE,)
    assert estimate.sizes == {STORE: 1024}
    assert estimate.total_bytes == 1024


def _capture_status(monkeypatch):
    statuses = []
    monkeypatch.setattr(nixos_upgrade, "write_status", statuses.append)
    return statuses


@pytest.mark.unit
def test_run_upgrade_invalid_ref_writes_failed(tmp_path, monkeypatch):
    ref_file = tmp_path / "ref"
    ref_file.write_text("release")
    statuses = _capture_status(monkeypatch)

    rc = nixos_upgrade.run_upgrade(ref_file, "imx462")

    assert rc == 1
    assert statuses == ["starting", "failed"]


@pytest.mark.unit
def test_run_upgrade_unavailable_writes_unavailable(tmp_path, monkeypatch):
    ref_file = tmp_path / "ref"
    ref_file.write_text(STORE)
    statuses = _capture_status(monkeypatch)
    monkeypatch.setattr(
        nixos_upgrade,
        "estimate_download",
        lambda _store: nixos_upgrade.DownloadEstimate({}, ()),
    )
    monkeypatch.setattr(nixos_upgrade, "write_sizes_file", lambda _estimate: None)
    monkeypatch.setattr(nixos_upgrade, "run_build", lambda _store, _estimate: 1)
    monkeypatch.setattr(nixos_upgrade, "store_path_available", lambda _store: False)

    rc = nixos_upgrade.run_upgrade(ref_file, "imx462")

    assert rc == 1
    assert statuses == ["starting", "unavailable"]


@pytest.mark.unit
def test_run_upgrade_build_failure_writes_failed(tmp_path, monkeypatch):
    ref_file = tmp_path / "ref"
    ref_file.write_text(STORE)
    statuses = _capture_status(monkeypatch)
    monkeypatch.setattr(
        nixos_upgrade,
        "estimate_download",
        lambda _store: nixos_upgrade.DownloadEstimate({}, ()),
    )
    monkeypatch.setattr(nixos_upgrade, "write_sizes_file", lambda _estimate: None)
    monkeypatch.setattr(nixos_upgrade, "run_build", lambda _store, _estimate: 1)
    monkeypatch.setattr(nixos_upgrade, "store_path_available", lambda _store: True)

    rc = nixos_upgrade.run_upgrade(ref_file, "imx462")

    assert rc == 1
    assert statuses == ["starting", "failed"]


@pytest.mark.unit
def test_run_upgrade_activation_failure_writes_failed(tmp_path, monkeypatch):
    ref_file = tmp_path / "ref"
    ref_file.write_text(STORE)
    statuses = _capture_status(monkeypatch)
    monkeypatch.setattr(
        nixos_upgrade,
        "estimate_download",
        lambda _store: nixos_upgrade.DownloadEstimate({}, ()),
    )
    monkeypatch.setattr(nixos_upgrade, "write_sizes_file", lambda _estimate: None)
    monkeypatch.setattr(nixos_upgrade, "run_build", lambda _store, _estimate: 0)
    monkeypatch.setattr(nixos_upgrade, "load_selection", dict)
    monkeypatch.setattr(
        nixos_upgrade,
        "activate_system",
        lambda _store, _camera: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    rc = nixos_upgrade.run_upgrade(ref_file, "imx462")

    assert rc == 1
    assert statuses == ["starting", "failed"]


@pytest.mark.unit
def test_run_upgrade_success_writes_rebooting_and_persists(tmp_path, monkeypatch):
    ref_file = tmp_path / "ref"
    ref_file.write_text(STORE)
    current_build = tmp_path / "current-build.json"
    statuses = _capture_status(monkeypatch)
    commands = []
    monkeypatch.setattr(nixos_upgrade, "CURRENT_BUILD_FILE", current_build)
    monkeypatch.setattr(
        nixos_upgrade,
        "estimate_download",
        lambda _store: nixos_upgrade.DownloadEstimate({}, ()),
    )
    monkeypatch.setattr(nixos_upgrade, "write_sizes_file", lambda _estimate: None)
    monkeypatch.setattr(nixos_upgrade, "run_build", lambda _store, _estimate: 0)
    monkeypatch.setattr(
        nixos_upgrade,
        "load_selection",
        lambda: {"version": "nixos-test", "label": "test", "channel": "unstable"},
    )
    monkeypatch.setattr(nixos_upgrade, "activate_system", lambda _store, _camera: None)
    monkeypatch.setattr(nixos_upgrade, "cleanup_old_generations", lambda: None)
    monkeypatch.setattr(
        nixos_upgrade,
        "command",
        lambda args, **_kwargs: commands.append(args),
    )

    rc = nixos_upgrade.run_upgrade(ref_file, "imx462")

    assert rc == 0
    assert statuses == ["starting", "rebooting"]
    assert commands == [["systemctl", "reboot"]]
    assert json.loads(current_build.read_text())["version"] == "nixos-test"


@pytest.mark.unit
def test_run_upgrade_reboot_failure_writes_failed(tmp_path, monkeypatch):
    ref_file = tmp_path / "ref"
    ref_file.write_text(STORE)
    current_build = tmp_path / "current-build.json"
    statuses = _capture_status(monkeypatch)
    monkeypatch.setattr(nixos_upgrade, "CURRENT_BUILD_FILE", current_build)
    monkeypatch.setattr(
        nixos_upgrade,
        "estimate_download",
        lambda _store: nixos_upgrade.DownloadEstimate({}, ()),
    )
    monkeypatch.setattr(nixos_upgrade, "write_sizes_file", lambda _estimate: None)
    monkeypatch.setattr(nixos_upgrade, "run_build", lambda _store, _estimate: 0)
    monkeypatch.setattr(nixos_upgrade, "load_selection", dict)
    monkeypatch.setattr(nixos_upgrade, "activate_system", lambda _store, _camera: None)
    monkeypatch.setattr(nixos_upgrade, "cleanup_old_generations", lambda: None)

    def fail_reboot(_args, **_kwargs):
        raise RuntimeError("reboot failed")

    monkeypatch.setattr(nixos_upgrade, "command", fail_reboot)

    rc = nixos_upgrade.run_upgrade(ref_file, "imx462")

    assert rc == 1
    assert statuses == ["starting", "rebooting", "failed"]
