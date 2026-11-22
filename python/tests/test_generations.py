"""Unit tests for PiFinder.generations: the ledger and the confirmed walk."""

import pytest

from PiFinder import generations


def _system(store, name, cameras=()):
    """A fake system toplevel with camera specialisations."""
    system = store / name
    system.mkdir(parents=True)
    for camera in cameras:
        spec = store / f"{name}-{camera}"
        spec.mkdir()
        (system / "specialisation").mkdir(exist_ok=True)
        (system / "specialisation" / camera).symlink_to(spec)
    return system


def _profile(tmp_path, systems):
    profile = tmp_path / "profiles"
    profile.mkdir()
    for number, system in enumerate(systems, start=1):
        (profile / f"system-{number}-link").symlink_to(system)
    return profile


def _ledger(tmp_path, paths):
    ledger = tmp_path / "confirmed-generations"
    ledger.write_text("".join(f"{p}\n" for p in paths))
    return ledger


@pytest.mark.unit
def test_recovery_mode_follows_the_flag(tmp_path):
    flag = tmp_path / "recovery-mode"
    assert not generations.recovery_mode_active(flag)
    flag.write_text("")
    assert generations.recovery_mode_active(flag)


@pytest.mark.unit
def test_missing_ledger_is_empty(tmp_path):
    assert generations.read_ledger(tmp_path / "none") == frozenset()


@pytest.mark.unit
def test_ledger_ignores_blank_lines(tmp_path):
    ledger = tmp_path / "ledger"
    ledger.write_text("/nix/store/a\n\n  /nix/store/b \n")
    assert generations.read_ledger(ledger) == {"/nix/store/a", "/nix/store/b"}


@pytest.mark.unit
def test_confirmed_system_finds_a_specialisation(tmp_path):
    system = _system(tmp_path / "store", "sys", cameras=["imx296"])
    spec = str((tmp_path / "store" / "sys-imx296").resolve())
    assert generations.confirmed_system(system, frozenset({spec})) == spec
    assert generations.confirmed_system(system, frozenset()) is None


@pytest.mark.unit
def test_newest_confirmed_takes_the_newest(tmp_path):
    store = tmp_path / "store"
    old, mid, new = (_system(store, n) for n in ("old", "mid", "new"))
    profile = _profile(tmp_path, [old, mid, new])
    ledger = _ledger(tmp_path, [old.resolve(), mid.resolve()])
    assert generations.newest_confirmed(profile, ledger) == mid.resolve()


@pytest.mark.unit
def test_newest_confirmed_skips_the_excluded_system(tmp_path):
    store = tmp_path / "store"
    old = _system(store, "old", cameras=["imx296"])
    new = _system(store, "new", cameras=["imx296"])
    profile = _profile(tmp_path, [old, new])
    ledger = _ledger(
        tmp_path,
        [(store / "old-imx296").resolve(), (store / "new-imx296").resolve()],
    )
    # The excluded system is the specialisation of the newest generation.
    result = generations.newest_confirmed(
        profile, ledger, exclude=str(store / "new-imx296")
    )
    assert result == (store / "old-imx296").resolve()


@pytest.mark.unit
def test_newest_confirmed_none_without_a_confirmed_generation(tmp_path):
    store = tmp_path / "store"
    profile = _profile(tmp_path, [_system(store, "a"), _system(store, "b")])
    assert generations.newest_confirmed(profile, _ledger(tmp_path, [])) is None


@pytest.mark.unit
def test_generation_links_sort_by_number(tmp_path):
    store = tmp_path / "store"
    systems = [_system(store, f"s{n}") for n in range(11)]
    profile = _profile(tmp_path, systems)
    numbers = [number for number, _link in generations.generation_links(profile)]
    assert numbers == list(range(11, 0, -1))
