"""Regression tests for cedar_detect shared-memory recovery on restart.

All cedar clients share one hard-coded segment name, so a second client on
the same host (e.g. an offline analysis script) can leave the server's
cached fd pointing at its own frozen image — the live solver then "solves"
that frame forever. A solver restart must always recover: clear whatever
segment exists at startup, and force the server to reopen the fresh one on
the first request. A killed solver similarly leaks its segment; the next
client must clear it instead of dying on FileExistsError on every solve.
"""

from multiprocessing import shared_memory
from types import SimpleNamespace

import pytest

import PiFinder.solver as solver_mod
from PiFinder.solver import PFCedarDetectClient


@pytest.mark.unit
def test_clear_stale_shmem_unlinks_leaked_segment(monkeypatch):
    # Unique name so the test never touches a real/live cedar_detect_image.
    name = "/cedar_detect_image_pftest"
    monkeypatch.setattr(solver_mod, "_CEDAR_DETECT_SHMEM_NAME", name)

    # Simulate a leak: created but never unlinked, as a killed solver leaves it.
    leaked = shared_memory.SharedMemory(name, create=True, size=16)
    leaked.close()

    client = object.__new__(PFCedarDetectClient)
    client._shmem = None  # __del__ inspects this attribute
    try:
        client._clear_stale_shmem()
        with pytest.raises(FileNotFoundError):
            shared_memory.SharedMemory(name)
        # Idempotent: clearing again when nothing is present must not raise.
        client._clear_stale_shmem()
    finally:
        try:
            stray = shared_memory.SharedMemory(name)
            stray.close()
            stray.unlink()
        except FileNotFoundError:
            pass


@pytest.mark.unit
def test_alloc_shmem_requests_reopen_on_fresh_segment(monkeypatch):
    # Restart recovery: the first allocation after startup must return True
    # so the request sets reopen_shmem and the server drops a cached fd that
    # may point at another client's (possibly unlinked) segment. Upstream's
    # _alloc_shmem returns False here — only PFCedarDetectClient's override
    # guarantees a restart always resynchronizes solver and server.
    name = "/cedar_detect_image_pftest_fresh"
    monkeypatch.setattr(
        "tetra3.cedar_detect_client.shared_memory",
        SimpleNamespace(
            SharedMemory=lambda _name, create=False, size=0: (
                shared_memory.SharedMemory(name, create=create, size=size)
            )
        ),
    )

    client = object.__new__(PFCedarDetectClient)
    client._shmem = None
    client._shmem_size = 0
    try:
        assert client._alloc_shmem(16) is True  # fresh segment → reopen
        assert client._alloc_shmem(16) is False  # unchanged → no reopen
        assert client._alloc_shmem(32) is True  # resized → reopen
    finally:
        client._del_shmem()
