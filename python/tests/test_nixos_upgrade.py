import json
import urllib.error

import pytest

from PiFinder import nixos_upgrade


STORE = "/nix/store/abc123-nixos-system-pifinder"


class _FakeResp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(outcomes):
    """Build a urlopen stub that returns/raises one outcome per cache probe.

    Each outcome is either an int HTTP status (-> a response) or an Exception
    instance to raise (a 404 HTTPError, a URLError, etc.).
    """
    calls = iter(outcomes)

    def _open(url, timeout=None):
        outcome = next(calls)
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResp(outcome)

    return _open


def _http_error(code):
    return urllib.error.HTTPError(
        url="https://cache/abc.narinfo", code=code, msg="x", hdrs=None, fp=None
    )


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
def test_parse_progress_event_extracts_byte_progress():
    line = '@nix {"action":"result","id":3,"type":105,"fields":[1024,4096,1,0]}'
    event = nixos_upgrade.parse_progress_event(line)
    assert event == nixos_upgrade.ProgressEvent("result", 3, None, None, 1024, 4096)


@pytest.mark.unit
def test_download_progress_tracks_bytes_and_label(monkeypatch):
    statuses: list[str] = []
    monkeypatch.setattr(
        nixos_upgrade, "write_status", lambda s, _f=None: statuses.append(s)
    )
    progress = nixos_upgrade._DownloadProgress(10_000_000, 2, None)
    progress.feed(
        f'@nix {{"action":"start","id":1,"type":100,'
        f'"text":"copying path \'{STORE}\' from cache"}}'
    )
    progress.feed(
        '@nix {"action":"result","id":1,"type":105,"fields":[5000000,8000000,1,0]}'
    )
    progress.feed('@nix {"action":"stop","id":1,"type":100}')

    # within-path byte movement, the package label, and never a crash on junk
    assert statuses and all(s.startswith("downloading ") for s in statuses)
    assert any("nixos-system-pifinder" in s for s in statuses)
    for bad in ["garbage", "@nix {oops", ""]:
        progress.feed(bad)


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
    monkeypatch.setattr(nixos_upgrade, "fetch_cache_public_keys", lambda: [])

    rc = nixos_upgrade.run_build(
        STORE,
        nixos_upgrade.DownloadEstimate(()),
        status_file=tmp_path / "status",
        log_file=tmp_path / "log",
    )

    assert rc == 0
    assert "--no-link" in started["args"]


@pytest.mark.unit
def test_estimate_download_parses_paths_and_total(monkeypatch):
    dry = (
        "these 1 paths will be fetched (0.0 KiB download, 12.5 MiB unpacked):\n"
        f"  {STORE}\n"
    )

    def fake_command(args, **kwargs):
        class Result:
            returncode = 0
            stdout = dry
            stderr = ""

        return Result()

    monkeypatch.setattr(nixos_upgrade, "command", fake_command)

    estimate = nixos_upgrade.estimate_download(STORE)

    assert estimate.paths == (STORE,)
    assert estimate.path_count == 1
    assert estimate.total_bytes == int(12.5 * 1024 * 1024)


def _capture_status(monkeypatch):
    statuses = []
    monkeypatch.setattr(nixos_upgrade, "write_status", statuses.append)
    return statuses


@pytest.mark.unit
def test_classify_local_path_is_available(monkeypatch):
    monkeypatch.setattr(nixos_upgrade, "path_exists", lambda _p: True)
    assert nixos_upgrade.classify_store_path(STORE) == nixos_upgrade.AVAILABLE


@pytest.mark.unit
def test_classify_cache_hit_is_available(monkeypatch):
    monkeypatch.setattr(nixos_upgrade, "path_exists", lambda _p: False)
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen([200]))
    assert nixos_upgrade.classify_store_path(STORE) == nixos_upgrade.AVAILABLE


@pytest.mark.unit
def test_classify_all_404_is_absent(monkeypatch):
    monkeypatch.setattr(nixos_upgrade, "path_exists", lambda _p: False)
    monkeypatch.setattr(
        "urllib.request.urlopen", _fake_urlopen([_http_error(404), _http_error(404)])
    )
    assert nixos_upgrade.classify_store_path(STORE) == nixos_upgrade.ABSENT


@pytest.mark.unit
def test_classify_connection_error_is_unreachable(monkeypatch):
    monkeypatch.setattr(nixos_upgrade, "path_exists", lambda _p: False)
    err = urllib.error.URLError("no route to host")
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen([err, err]))
    assert nixos_upgrade.classify_store_path(STORE) == nixos_upgrade.UNREACHABLE


@pytest.mark.unit
def test_classify_partial_unreachable_is_not_absent(monkeypatch):
    # One cache says 404, the other can't be reached: the build might still be
    # on the unreachable cache, so this must be retryable, not "gone".
    monkeypatch.setattr(nixos_upgrade, "path_exists", lambda _p: False)
    outcomes = [_http_error(404), urllib.error.URLError("timeout")]
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(outcomes))
    assert nixos_upgrade.classify_store_path(STORE) == nixos_upgrade.UNREACHABLE


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
        lambda _store: nixos_upgrade.DownloadEstimate(()),
    )
    monkeypatch.setattr(nixos_upgrade, "run_build", lambda _store, _estimate: 1)
    monkeypatch.setattr(
        nixos_upgrade, "classify_store_path", lambda _store: nixos_upgrade.ABSENT
    )

    rc = nixos_upgrade.run_upgrade(ref_file, "imx462")

    assert rc == 1
    assert statuses == ["starting", "unavailable"]


@pytest.mark.unit
def test_run_upgrade_unreachable_writes_connfail(tmp_path, monkeypatch):
    ref_file = tmp_path / "ref"
    ref_file.write_text(STORE)
    statuses = _capture_status(monkeypatch)
    monkeypatch.setattr(
        nixos_upgrade,
        "estimate_download",
        lambda _store: nixos_upgrade.DownloadEstimate(()),
    )
    monkeypatch.setattr(nixos_upgrade, "run_build", lambda _store, _estimate: 1)
    monkeypatch.setattr(
        nixos_upgrade, "classify_store_path", lambda _store: nixos_upgrade.UNREACHABLE
    )

    rc = nixos_upgrade.run_upgrade(ref_file, "imx462")

    assert rc == 1
    assert statuses == ["starting", "connfail"]


@pytest.mark.unit
def test_run_upgrade_build_failure_writes_failed(tmp_path, monkeypatch):
    ref_file = tmp_path / "ref"
    ref_file.write_text(STORE)
    statuses = _capture_status(monkeypatch)
    monkeypatch.setattr(
        nixos_upgrade,
        "estimate_download",
        lambda _store: nixos_upgrade.DownloadEstimate(()),
    )
    monkeypatch.setattr(nixos_upgrade, "run_build", lambda _store, _estimate: 1)
    monkeypatch.setattr(
        nixos_upgrade, "classify_store_path", lambda _store: nixos_upgrade.AVAILABLE
    )

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
        lambda _store: nixos_upgrade.DownloadEstimate(()),
    )
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
        lambda _store: nixos_upgrade.DownloadEstimate(()),
    )
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
        lambda _store: nixos_upgrade.DownloadEstimate(()),
    )
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


def _setup_activation(tmp_path, monkeypatch, camera_type, specialisations):
    """Fixture for activate_system: fake store path, persisted camera, and
    captured command()/arm_trial_marker() calls."""
    store = tmp_path / "store" / "new-system"
    store.mkdir(parents=True)
    (store / "bin").mkdir()
    for cam in specialisations:
        (store / "specialisation" / cam / "bin").mkdir(parents=True)

    camera_file = tmp_path / "camera-type"
    if camera_type is not None:
        camera_file.write_text(camera_type + "\n")
    monkeypatch.setattr(nixos_upgrade, "CAMERA_TYPE_FILE", camera_file)

    calls = []
    monkeypatch.setattr(
        nixos_upgrade, "command", lambda args, **kw: calls.append(list(args))
    )
    armed = []
    monkeypatch.setattr(nixos_upgrade, "arm_trial_marker", armed.append)
    monkeypatch.setattr(nixos_upgrade, "write_status", lambda *_a, **_k: None)
    return store, calls, armed


@pytest.mark.unit
def test_activate_boots_specialisation_even_when_old_base_matches(
    tmp_path, monkeypatch
):
    """Regression: device persisted imx477 while upgrading from an imx477-BASE
    build onto an imx462-base build. Comparing against the old build's base
    (--default-camera imx477) concluded 'camera is the base' and booted the
    new imx462 base, killing the camera. The decision must instead ask the
    NEW store path whether it carries a specialisation for the camera."""
    store, calls, armed = _setup_activation(tmp_path, monkeypatch, "imx477", ["imx477"])

    nixos_upgrade.activate_system(str(store), "imx477")

    spec = store / "specialisation" / "imx477"
    assert armed == [spec]
    assert [str(spec / "bin/switch-to-configuration"), "boot"] in calls
    assert calls[-1][-1] == "imx477"


@pytest.mark.unit
def test_activate_base_branch_when_no_specialisation(tmp_path, monkeypatch):
    store, calls, armed = _setup_activation(tmp_path, monkeypatch, "imx462", ["imx477"])

    nixos_upgrade.activate_system(str(store), "imx477")

    assert armed == [nixos_upgrade.Path(str(store))]
    assert [str(store / "bin/switch-to-configuration"), "boot"] in calls
    assert calls[-1][-1] == "imx462"


@pytest.mark.unit
def test_set_extlinux_default_prefers_new_builds_helper(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        nixos_upgrade, "command", lambda args, **kw: calls.append(list(args))
    )
    store = tmp_path / "sys"
    helper = store / "sw" / "bin" / "set-extlinux-default"
    helper.parent.mkdir(parents=True)
    helper.write_text("#!/bin/sh\n")

    nixos_upgrade.set_extlinux_default("imx477", str(store))
    assert calls[-1] == [str(helper), "imx477"]

    nixos_upgrade.set_extlinux_default("imx477", str(tmp_path / "missing"))
    assert calls[-1] == ["set-extlinux-default", "imx477"]
