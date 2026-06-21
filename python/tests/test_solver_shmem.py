"""Regression test for stale cedar_detect shared-memory cleanup.

A solver process that is killed leaks its POSIX shmem segment; the next
PFCedarDetectClient must clear it at startup instead of dying on
FileExistsError on every solve.
"""

from multiprocessing import shared_memory

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
