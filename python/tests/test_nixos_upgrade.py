import json
import subprocess
import urllib.error

from pathlib import Path

import pytest

from PiFinder import nixos_upgrade


STORE = "/nix/store/abc123-nixos-system-pifinder"

# The real functions, for their own tests; every other test gets no-ops so
# that no test calls systemctl or btrfs on the host.
_REAL_SNAPSHOT_USER_DATA = nixos_upgrade.snapshot_user_data
_REAL_STOP_BTRFS_TIDY = nixos_upgrade.stop_btrfs_tidy


@pytest.fixture(autouse=True)
def _no_host_btrfs(monkeypatch):
    monkeypatch.setattr(nixos_upgrade, "snapshot_user_data", lambda _store: None)
    monkeypatch.setattr(nixos_upgrade, "stop_btrfs_tidy", lambda: None)


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
def test_parse_progress_event_extracts_copy_source():
    line = (
        '@nix {"action":"start","id":7,"type":100,'
        f'"fields":["{STORE}","file:///var/lib/x/cache","local"],'
        f'"text":"copying path \'{STORE}\' from cache"}}'
    )
    event = nixos_upgrade.parse_progress_event(line)
    assert event is not None
    assert event.source == "file:///var/lib/x/cache"
    assert event.path == STORE


@pytest.mark.unit
def test_download_progress_skips_the_local_patch_cache(monkeypatch):
    statuses: list[str] = []
    monkeypatch.setattr(
        nixos_upgrade, "write_status", lambda s, _f=None: statuses.append(s)
    )
    progress = nixos_upgrade._DownloadProgress(
        10_000_000, 2, None, local_source="file:///var/lib/x/cache", local_total=1
    )
    progress.feed(
        '@nix {"action":"start","id":1,"type":100,'
        f'"fields":["{STORE}","file:///var/lib/x/cache/","local"]}}'
    )
    progress.feed(
        '@nix {"action":"result","id":1,"type":105,"fields":[9000000,9000000,1,0]}'
    )
    progress.feed('@nix {"action":"stop","id":1}')
    # The local copy is the "installing" step, in paths, not a download.
    assert [x.split(" ")[:2] for x in statuses] == [
        ["installing", "0/1"],
        ["installing", "1/1"],
    ]
    progress.feed(
        '@nix {"action":"start","id":2,"type":100,'
        f'"fields":["{STORE}","https://cache.nixos.org","local"]}}'
    )
    progress.feed(
        '@nix {"action":"result","id":2,"type":105,"fields":[4000000,4000000,1,0]}'
    )
    assert statuses[-1].startswith("downloading 4000000/10000000")


@pytest.mark.unit
def test_run_build_total_leaves_out_patched_bytes(monkeypatch, tmp_path):
    class FakeProcess:
        stdout = iter(())

        def wait(self):
            return 0

    monkeypatch.setattr(
        nixos_upgrade.subprocess, "Popen", lambda args, **kw: FakeProcess()
    )
    status = tmp_path / "status"
    nixos_upgrade.run_build(
        STORE,
        nixos_upgrade.DownloadEstimate((STORE,) * 3, 30_000_000),
        status_file=status,
        log_file=tmp_path / "log",
        substituter="file:///var/lib/x/cache",
        patched_bytes=26_000_000,
        patched_paths=2,
    )
    # nix installs the 2 patched paths first, then downloads the rest.
    assert status.read_text().strip() == "installing 0/2"


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
    progress.feed('@nix {"action":"stop","id":1}')

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
    monkeypatch.setattr(nixos_upgrade, "run_build", lambda _store, _estimate, **_kw: 1)
    monkeypatch.setattr(
        nixos_upgrade, "classify_store_path", lambda _store: nixos_upgrade.ABSENT
    )

    rc = nixos_upgrade.run_upgrade(ref_file, "imx462")

    assert rc == 1
    assert statuses == ["starting", "checking", "unavailable"]


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
    monkeypatch.setattr(nixos_upgrade, "run_build", lambda _store, _estimate, **_kw: 1)
    monkeypatch.setattr(
        nixos_upgrade, "classify_store_path", lambda _store: nixos_upgrade.UNREACHABLE
    )

    rc = nixos_upgrade.run_upgrade(ref_file, "imx462")

    assert rc == 1
    assert statuses == ["starting", "checking", "connfail"]


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
    monkeypatch.setattr(nixos_upgrade, "run_build", lambda _store, _estimate, **_kw: 1)
    monkeypatch.setattr(
        nixos_upgrade, "classify_store_path", lambda _store: nixos_upgrade.AVAILABLE
    )

    rc = nixos_upgrade.run_upgrade(ref_file, "imx462")

    assert rc == 1
    assert statuses == ["starting", "checking", "failed"]


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
    monkeypatch.setattr(nixos_upgrade, "run_build", lambda _store, _estimate, **_kw: 0)
    monkeypatch.setattr(nixos_upgrade, "load_selection", dict)
    monkeypatch.setattr(nixos_upgrade, "check_root_mountable", lambda _system: None)
    monkeypatch.setattr(
        nixos_upgrade,
        "activate_system",
        lambda _store, _camera: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    rc = nixos_upgrade.run_upgrade(ref_file, "imx462")

    assert rc == 1
    assert statuses == ["starting", "checking", "failed"]


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
    monkeypatch.setattr(nixos_upgrade, "run_build", lambda _store, _estimate, **_kw: 0)
    monkeypatch.setattr(
        nixos_upgrade,
        "load_selection",
        lambda: {"version": "nixos-test", "label": "test", "channel": "unstable"},
    )
    monkeypatch.setattr(nixos_upgrade, "check_root_mountable", lambda _system: None)
    monkeypatch.setattr(nixos_upgrade, "activate_system", lambda _store, _camera: None)
    monkeypatch.setattr(nixos_upgrade, "cleanup_old_generations", lambda: None)
    monkeypatch.setattr(
        nixos_upgrade,
        "command",
        lambda args, **_kwargs: commands.append(args),
    )

    rc = nixos_upgrade.run_upgrade(ref_file, "imx462")

    assert rc == 0
    assert statuses == ["starting", "checking", "rebooting"]
    assert commands[-1] == ["systemctl", "reboot"]
    assert commands[0][:2] == ["pifinder-bootcount", "arm"]
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
    monkeypatch.setattr(nixos_upgrade, "run_build", lambda _store, _estimate, **_kw: 0)
    monkeypatch.setattr(nixos_upgrade, "load_selection", dict)
    monkeypatch.setattr(nixos_upgrade, "check_root_mountable", lambda _system: None)
    monkeypatch.setattr(nixos_upgrade, "activate_system", lambda _store, _camera: None)
    monkeypatch.setattr(nixos_upgrade, "cleanup_old_generations", lambda: None)

    def fail_reboot(_args, **_kwargs):
        raise RuntimeError("reboot failed")

    monkeypatch.setattr(nixos_upgrade, "command", fail_reboot)

    rc = nixos_upgrade.run_upgrade(ref_file, "imx462")

    assert rc == 1
    assert statuses == ["starting", "checking", "rebooting", "failed"]


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


def test_run_build_passes_staged_cache_as_substituter(monkeypatch, tmp_path):
    started = {}

    class FakeProcess:
        stdout = iter(())

        def wait(self):
            return 0

    def fake_popen(args, **kwargs):
        started["args"] = args
        return FakeProcess()

    monkeypatch.setattr(nixos_upgrade.subprocess, "Popen", fake_popen)
    nixos_upgrade.run_build(
        STORE,
        nixos_upgrade.DownloadEstimate(()),
        status_file=tmp_path / "status",
        log_file=tmp_path / "log",
        substituter="file:///var/lib/pifinder/delta-work/x/cache",
    )
    args = started["args"]
    i = args.index("extra-substituters")
    assert args[i - 1] == "--option"
    assert args[i + 1] == "file:///var/lib/pifinder/delta-work/x/cache"
    assert "--no-check-sigs" not in args


def _system_with_fstab(tmp_path, line):
    system = tmp_path / "system"
    (system / "etc").mkdir(parents=True)
    (system / "etc" / "fstab").write_text(
        "# comment\n" + line + "\n/dev/disk/by-label/FIRMWARE /boot/firmware vfat\n"
    )
    return system


@pytest.mark.unit
def test_fstab_root_reads_the_root_line(tmp_path):
    system = _system_with_fstab(tmp_path, "/dev/mmcblk0p2 / auto x-initrd.mount 0 1")
    assert nixos_upgrade.fstab_root(system) == ("/dev/mmcblk0p2", "auto")
    assert nixos_upgrade.fstab_root(tmp_path / "missing") is None


@pytest.mark.unit
def test_mounted_root_takes_the_top_entry(tmp_path):
    mounts = tmp_path / "mounts"
    mounts.write_text(
        "rootfs / rootfs rw 0 0\n"
        "/dev/mmcblk0p2 / btrfs rw,noatime 0 0\n"
        "tmpfs /run tmpfs rw 0 0\n"
    )
    assert nixos_upgrade.mounted_root(mounts) == ("/dev/mmcblk0p2", "btrfs")


@pytest.mark.unit
def test_check_root_mountable_accepts_the_mounted_device(tmp_path, monkeypatch):
    disk = tmp_path / "mmcblk0p2"
    disk.touch()
    system = _system_with_fstab(tmp_path, f"{disk} / auto x-initrd.mount 0 1")
    monkeypatch.setattr(nixos_upgrade, "mounted_root", lambda: (str(disk), "btrfs"))
    nixos_upgrade.check_root_mountable(system)


@pytest.mark.unit
def test_check_root_mountable_rejects_a_missing_label(tmp_path, monkeypatch):
    disk = tmp_path / "mmcblk0p2"
    disk.touch()
    system = _system_with_fstab(
        tmp_path, f"{tmp_path}/by-label/NIXOS_SD / ext4 x-initrd.mount 0 1"
    )
    monkeypatch.setattr(nixos_upgrade, "mounted_root", lambda: (str(disk), "btrfs"))
    with pytest.raises(nixos_upgrade.UpgradeError, match="mounts / from"):
        nixos_upgrade.check_root_mountable(system)


@pytest.mark.unit
def test_check_root_mountable_rejects_another_fs_type(tmp_path, monkeypatch):
    disk = tmp_path / "mmcblk0p2"
    disk.touch()
    system = _system_with_fstab(tmp_path, f"{disk} / ext4 x-initrd.mount 0 1")
    monkeypatch.setattr(nixos_upgrade, "mounted_root", lambda: (str(disk), "btrfs"))
    with pytest.raises(nixos_upgrade.UpgradeError, match="as ext4"):
        nixos_upgrade.check_root_mountable(system)


@pytest.mark.unit
def test_run_upgrade_refuses_a_build_that_cannot_mount_root(tmp_path, monkeypatch):
    ref_file = tmp_path / "ref"
    ref_file.write_text(STORE)
    statuses = _capture_status(monkeypatch)
    monkeypatch.setattr(
        nixos_upgrade,
        "estimate_download",
        lambda _store: nixos_upgrade.DownloadEstimate(()),
    )
    monkeypatch.setattr(nixos_upgrade, "run_build", lambda _store, _estimate, **_kw: 0)
    monkeypatch.setattr(nixos_upgrade, "load_selection", dict)
    activated = []
    monkeypatch.setattr(
        nixos_upgrade, "activate_system", lambda *args: activated.append(args)
    )

    def _refuse(_system):
        raise nixos_upgrade.UpgradeError("mounts / from NIXOS_SD")

    monkeypatch.setattr(nixos_upgrade, "check_root_mountable", _refuse)

    rc = nixos_upgrade.run_upgrade(ref_file, "imx462")

    assert rc == 1
    assert activated == []
    assert statuses == ["starting", "checking", "failed"]


# ---------------------------------------------------------------------------
# PiFinder_data snapshot before the switch (A9) and the btrfs balance stop (A8)


class _FakeBtrfs:
    """Fake command(): 'subvolume show' answers is_subvolume; 'snapshot'
    creates the target directory; 'delete' removes it."""

    def __init__(self, is_subvolume=True, snapshot_rc=0):
        self.is_subvolume = is_subvolume
        self.snapshot_rc = snapshot_rc
        self.calls: list[list[str]] = []

    def __call__(self, args, **_kw):
        self.calls.append(args)
        rc = 0
        if args[:3] == ["btrfs", "subvolume", "show"]:
            rc = 0 if self.is_subvolume else 1
        elif args[:3] == ["btrfs", "subvolume", "snapshot"]:
            rc = self.snapshot_rc
            if rc == 0:
                Path(args[-1]).mkdir()
        elif args[:3] == ["btrfs", "subvolume", "delete"]:
            Path(args[-1]).rmdir()
        return subprocess.CompletedProcess(args, rc, "", "boom" if rc else "")


@pytest.mark.unit
def test_snapshot_name_sorts_by_time():
    from datetime import datetime, timezone

    name = nixos_upgrade.snapshot_name(
        "/nix/store/l36zd40lf3nrg41crkdz478iq1ww0zh5-nixos-system-pifinder",
        datetime(2026, 9, 27, 9, 8, 7, tzinfo=timezone.utc),
    )
    assert name == "PiFinder_data-20260927T090807Z-l36zd40l"


@pytest.mark.unit
def test_snapshot_skipped_when_not_a_subvolume(monkeypatch, tmp_path):
    fake = _FakeBtrfs(is_subvolume=False)
    monkeypatch.setattr(nixos_upgrade, "command", fake)
    got = _REAL_SNAPSHOT_USER_DATA(STORE, tmp_path / "data", tmp_path / "snaps")
    assert got is None
    assert [c[:3] for c in fake.calls] == [["btrfs", "subvolume", "show"]]
    assert not (tmp_path / "snaps").exists()


@pytest.mark.unit
def test_snapshot_taken_read_only_and_old_ones_pruned(monkeypatch, tmp_path):
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    for old in ("20260901T000000Z-aaaaaaaa", "20260902T000000Z-bbbbbbbb"):
        (snaps / f"PiFinder_data-{old}").mkdir()
    (snaps / "other").mkdir()
    fake = _FakeBtrfs()
    monkeypatch.setattr(nixos_upgrade, "command", fake)

    got = _REAL_SNAPSHOT_USER_DATA(STORE, tmp_path / "data", snaps, keep=2)

    assert got is not None and Path(got).name.startswith("PiFinder_data-")
    snapshot_call = next(c for c in fake.calls if c[2] == "snapshot")
    assert snapshot_call[3] == "-r"
    kept = sorted(p.name for p in snaps.iterdir())
    assert kept == ["PiFinder_data-20260902T000000Z-bbbbbbbb", Path(got).name, "other"]


@pytest.mark.unit
def test_snapshot_failure_never_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(nixos_upgrade, "command", _FakeBtrfs(snapshot_rc=1))
    assert _REAL_SNAPSHOT_USER_DATA(STORE, tmp_path / "d", tmp_path / "s") is None

    def missing(args, **_kw):
        raise FileNotFoundError("btrfs")

    monkeypatch.setattr(nixos_upgrade, "command", missing)
    assert _REAL_SNAPSHOT_USER_DATA(STORE, tmp_path / "d", tmp_path / "s") is None
    _REAL_STOP_BTRFS_TIDY()


@pytest.mark.unit
def test_stop_btrfs_tidy_stops_the_unit(monkeypatch):
    calls = []
    monkeypatch.setattr(
        nixos_upgrade, "command", lambda args, **_kw: calls.append(args)
    )
    _REAL_STOP_BTRFS_TIDY()
    assert calls == [
        ["systemctl", "stop", "--no-ask-password", "pifinder-btrfs-tidy.service"]
    ]


@pytest.mark.unit
def test_run_upgrade_snapshots_before_activation(tmp_path, monkeypatch):
    ref_file = tmp_path / "ref"
    ref_file.write_text(STORE)
    _capture_status(monkeypatch)
    order: list[str] = []
    monkeypatch.setattr(
        nixos_upgrade, "stop_btrfs_tidy", lambda: order.append("stop-tidy")
    )
    monkeypatch.setattr(
        nixos_upgrade,
        "estimate_download",
        lambda _store: nixos_upgrade.DownloadEstimate(()),
    )
    monkeypatch.setattr(nixos_upgrade, "run_build", lambda _s, _e, **_kw: 0)
    monkeypatch.setattr(nixos_upgrade, "check_root_mountable", lambda _system: None)
    monkeypatch.setattr(
        nixos_upgrade, "snapshot_user_data", lambda _store: order.append("snapshot")
    )
    monkeypatch.setattr(
        nixos_upgrade,
        "activate_system",
        lambda _store, _camera: order.append("activate"),
    )
    monkeypatch.setattr(nixos_upgrade, "persist_current_build", lambda *_a: None)
    monkeypatch.setattr(nixos_upgrade, "cleanup_old_generations", lambda: None)
    monkeypatch.setattr(nixos_upgrade, "command", lambda *a, **kw: None)

    nixos_upgrade.run_upgrade(ref_file, "imx462")

    assert order == ["stop-tidy", "snapshot", "activate"]


@pytest.mark.unit
def test_arm_boot_counter_names_the_running_system(tmp_path, monkeypatch):
    system = tmp_path / "system"
    system.mkdir()
    link = tmp_path / "current-system"
    link.symlink_to(system)
    calls = []
    monkeypatch.setattr(
        nixos_upgrade, "command", lambda args, **_kw: calls.append(args)
    )
    nixos_upgrade.arm_boot_counter(link)
    assert calls == [["pifinder-bootcount", "arm", str(system)]]


@pytest.mark.unit
def test_arm_boot_counter_never_raises(monkeypatch):
    def boom(_args, **_kw):
        raise FileNotFoundError("pifinder-bootcount")

    monkeypatch.setattr(nixos_upgrade, "command", boom)
    nixos_upgrade.arm_boot_counter()


@pytest.mark.unit
def test_write_status_replaces_the_file_in_one_step(tmp_path, monkeypatch):
    status = tmp_path / "upgrade-status"
    status.write_text("patching applying 1/41")
    seen = []
    real_replace = nixos_upgrade.os.replace

    def spy_replace(src, dst):
        # Before the swap the old line is still complete; never empty.
        seen.append(Path(dst).read_text())
        real_replace(src, dst)

    monkeypatch.setattr(nixos_upgrade.os, "replace", spy_replace)
    nixos_upgrade.write_status("patching applying 2/41", status)
    assert seen == ["patching applying 1/41"]
    assert status.read_text() == "patching applying 2/41"
    assert [p.name for p in tmp_path.iterdir()] == ["upgrade-status"]


@pytest.mark.unit
def test_remember_build_label_keeps_the_newest(tmp_path, monkeypatch):
    labels = tmp_path / "build-labels.json"
    monkeypatch.setattr(nixos_upgrade, "MAX_BUILD_LABELS", 3)
    for i in range(5):
        nixos_upgrade.remember_build_label(f"/nix/store/p{i}", f"L{i}", labels)
    nixos_upgrade.remember_build_label("/nix/store/p2", "L2-again", labels)
    stored = json.loads(labels.read_text())
    assert list(stored) == ["/nix/store/p3", "/nix/store/p4", "/nix/store/p2"]
    assert stored["/nix/store/p2"] == "L2-again"


@pytest.mark.unit
def test_remember_build_label_survives_a_broken_file(tmp_path):
    labels = tmp_path / "build-labels.json"
    labels.write_text("{not json")
    nixos_upgrade.remember_build_label("/nix/store/a", "v3.1.1-beta", labels)
    assert json.loads(labels.read_text()) == {"/nix/store/a": "v3.1.1-beta"}


@pytest.mark.unit
def test_persist_current_build_labels_the_new_and_the_left_build(tmp_path, monkeypatch):
    current = tmp_path / "current-build.json"
    labels = tmp_path / "build-labels.json"
    monkeypatch.setattr(nixos_upgrade, "CURRENT_BUILD_FILE", current)
    monkeypatch.setattr(nixos_upgrade, "BUILD_LABELS_FILE", labels)
    monkeypatch.setattr(nixos_upgrade.remember_build_label, "__defaults__", (labels,))
    current.write_text(
        json.dumps({"store_path": "/nix/store/old", "version": "PR#379-aaa"})
    )
    nixos_upgrade.persist_current_build(
        "/nix/store/new", {"label": "PR#534-bbb", "version": "PR#534-bbb"}
    )
    assert json.loads(labels.read_text()) == {
        "/nix/store/old": "PR#379-aaa",
        "/nix/store/new": "PR#534-bbb",
    }


# ---------------------------------------------------------------------------
# The "checking" step from the closure in the /update-start reply

_LIB = "/nix/store/def456-glibc-2.42"
_APP = "/nix/store/ghi789-pifinder-src"
_CLOSURE = ((STORE, 1000), (_LIB, 2000), (_APP, 4000))


class _FakeValidity:
    """Fake command() for `nix-store --check-validity --print-invalid`."""

    def __init__(self, invalid, rc=0):
        self.invalid = set(invalid)
        self.rc = rc
        self.batches: list[list[str]] = []

    def __call__(self, args, **_kw):
        assert args[:3] == ["nix-store", "--check-validity", "--print-invalid"]
        paths = args[3:]
        self.batches.append(paths)
        return subprocess.CompletedProcess(
            args, self.rc, "".join(f"{p}\n" for p in paths if p in self.invalid), ""
        )


@pytest.mark.unit
def test_estimate_from_closure_counts_the_invalid_paths(monkeypatch):
    fake = _FakeValidity(invalid={STORE, _APP})
    monkeypatch.setattr(nixos_upgrade, "command", fake)
    seen = []

    estimate = nixos_upgrade.estimate_from_closure(
        STORE, _CLOSURE, progress=lambda d, t: seen.append((d, t)), batch=2
    )

    assert estimate == nixos_upgrade.DownloadEstimate((STORE, _APP), 5000)
    assert fake.batches == [[STORE, _LIB], [_APP]]
    assert seen == [(2, 3), (3, 3)]


@pytest.mark.unit
def test_estimate_from_closure_none_when_the_check_fails(monkeypatch):
    monkeypatch.setattr(nixos_upgrade, "command", _FakeValidity(invalid=(), rc=1))
    assert nixos_upgrade.estimate_from_closure(STORE, _CLOSURE) is None


@pytest.mark.unit
def test_estimate_from_closure_none_for_another_toplevel(monkeypatch):
    def _no_command(*_a, **_kw):
        raise AssertionError("no check for a closure of another build")

    monkeypatch.setattr(nixos_upgrade, "command", _no_command)
    assert nixos_upgrade.estimate_from_closure(STORE, ((_LIB, 1),)) is None


def _upgrade_until_build(tmp_path, monkeypatch, session, check_rc=0):
    """run_upgrade up to the build, which fails; returns the statuses, the
    estimate the build got, and whether the dry run ran."""
    ref_file = tmp_path / "ref"
    ref_file.write_text(STORE)
    statuses = _capture_status(monkeypatch)
    monkeypatch.setattr(nixos_upgrade.delta_updates, "open_session", lambda _s: session)
    monkeypatch.setattr(
        nixos_upgrade, "command", _FakeValidity(invalid={_APP}, rc=check_rc)
    )
    dry_runs = []

    def _dry_run(_store):
        dry_runs.append(_store)
        return nixos_upgrade.DownloadEstimate(())

    monkeypatch.setattr(nixos_upgrade, "estimate_download", _dry_run)
    built = {}

    def _build(_store, estimate, **_kw):
        built["estimate"] = estimate
        return 1

    monkeypatch.setattr(nixos_upgrade, "run_build", _build)
    monkeypatch.setattr(
        nixos_upgrade, "classify_store_path", lambda _store: nixos_upgrade.ABSENT
    )
    nixos_upgrade.run_upgrade(ref_file, "imx462")
    return statuses, built["estimate"], dry_runs


@pytest.mark.unit
def test_run_upgrade_checks_the_closure_with_a_count(tmp_path, monkeypatch):
    session = nixos_upgrade.delta_updates.UpdateSession("tok", _CLOSURE)
    statuses, estimate, dry_runs = _upgrade_until_build(tmp_path, monkeypatch, session)

    assert statuses == ["starting", "checking", "checking 3/3", "unavailable"]
    assert estimate == nixos_upgrade.DownloadEstimate((_APP,), 4000)
    assert dry_runs == []


@pytest.mark.unit
def test_run_upgrade_dry_run_when_the_check_fails(tmp_path, monkeypatch):
    session = nixos_upgrade.delta_updates.UpdateSession("tok", _CLOSURE)
    statuses, _estimate, dry_runs = _upgrade_until_build(
        tmp_path, monkeypatch, session, check_rc=1
    )

    assert statuses == ["starting", "checking", "checking", "unavailable"]
    assert dry_runs == [STORE]


@pytest.mark.unit
def test_run_upgrade_dry_run_without_a_closure(tmp_path, monkeypatch):
    session = nixos_upgrade.delta_updates.UpdateSession("tok")
    statuses, _estimate, dry_runs = _upgrade_until_build(tmp_path, monkeypatch, session)

    assert statuses == ["starting", "checking", "unavailable"]
    assert dry_runs == [STORE]
