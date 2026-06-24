"""Single-instance lock tests.

Verifies the flock-based guard: a second acquirer is refused, and — crucially
for field use — a lock left behind by a dead holder does NOT block a fresh
start (the kernel released it when the holder's fd closed). Tests pass an
isolated lock_dir so they never touch the real tmpfs lock.
"""

import errno
import fcntl
import os
from pathlib import Path

import pytest

from PiFinder import utils


@pytest.mark.unit
def test_second_acquire_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "_instance_lock_file", None)

    assert utils.acquire_single_instance_lock(lock_dir=tmp_path) is True
    # A second acquisition uses a fresh fd, exactly like another process would,
    # and flock denies it while the first holder is alive.
    assert utils.acquire_single_instance_lock(lock_dir=tmp_path) is False
    # The lock file records the holder pid for diagnostics.
    assert (tmp_path / "pifinder.lock").read_text().strip().isdigit()


@pytest.mark.unit
def test_stale_lock_file_does_not_block(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "_instance_lock_file", None)

    # Simulate a crashed run: a lock file with a dead pid and NO live flock.
    (tmp_path / "pifinder.lock").write_text("999999\n")

    # A fresh start must acquire cleanly — a leftover file alone never blocks.
    assert utils.acquire_single_instance_lock(lock_dir=tmp_path) is True


@pytest.mark.unit
def test_lock_released_when_holder_fd_closes(tmp_path, monkeypatch):
    lock_path = tmp_path / "pifinder.lock"

    # Hold the lock on an independent fd, then close it (mimics a process dying).
    holder = open(lock_path, "a+")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    holder.close()

    monkeypatch.setattr(utils, "_instance_lock_file", None)
    assert utils.acquire_single_instance_lock(lock_dir=tmp_path) is True


@pytest.mark.unit
def test_runtime_lock_dir_prefers_tmpfs_or_none():
    # RAM-backed /dev/shm when available, else None (never the SD-card data dir).
    d = utils.runtime_lock_dir()
    shm = Path("/dev/shm")
    if shm.is_dir() and os.access(shm, os.W_OK):
        assert d == shm
    else:
        assert d is None


@pytest.mark.unit
def test_no_lock_dir_fails_open(monkeypatch):
    # No tmpfs available -> skip locking, never block startup.
    monkeypatch.setattr(utils, "runtime_lock_dir", lambda: None)
    monkeypatch.setattr(utils, "_instance_lock_file", None)
    assert utils.acquire_single_instance_lock() is True


@pytest.mark.unit
def test_flock_mechanism_error_fails_open(tmp_path, monkeypatch):
    # A flock failure that is NOT "already locked" must not block startup.
    def boom(*_args, **_kwargs):
        raise OSError(errno.ENOLCK, "no locks available")

    monkeypatch.setattr(fcntl, "flock", boom)
    monkeypatch.setattr(utils, "_instance_lock_file", None)
    assert utils.acquire_single_instance_lock(lock_dir=tmp_path) is True
