"""
Unit tests for PFCedarDetectClient's shared-memory failure recovery.

Field condition being modelled: systemd-logind's ``RemoveIPC=yes`` (the
default) deletes every POSIX shared-memory segment the ``pifinder`` user
owns as soon as that user's last login session ends — a plain SSH logout
is enough, because the PiFinder services run as that user without a
login session of their own. The cedar-detect server then can't open the
segment by name (gRPC INTERNAL), and the client's cleanup used to raise
``FileNotFoundError`` from ``unlink()`` before it could disable the
shared-memory path — wedging every subsequent solve until restart
(discovered in the battery-runtime bench campaign as "solves die at the
cable pull": the SSH logout happened seconds beside the pull).

No cedar-detect server is needed: the gRPC stub is faked, but the
shared-memory segment and the protobuf requests are real.
"""

import logging
import types

import grpc
import numpy as np
import pytest

from multiprocessing import shared_memory

from PiFinder.solver import _CEDAR_DETECT_SHMEM_NAME, PFCedarDetectClient


def _bare_client():
    """A PFCedarDetectClient without __init__ (no server, no subprocess)."""
    client = PFCedarDetectClient.__new__(PFCedarDetectClient)
    client._subprocess = None
    client._stub = None
    client._shmem = None
    client._shmem_size = 0
    client._use_shmem = True
    return client


class _VanishedSegment:
    """Stands in for a segment logind already removed from /dev/shm."""

    def close(self):
        pass

    def unlink(self):
        raise FileNotFoundError(2, "No such file or directory")


class _InternalRpcError(grpc.RpcError):
    """The status the server returns when the shmem name can't be opened."""

    def code(self):
        return grpc.StatusCode.INTERNAL

    def details(self):
        return 'Could not open shared memory at "/cedar_detect_image": errno 2'


@pytest.mark.unit
def test_del_shmem_tolerates_vanished_segment():
    """A segment already gone from /dev/shm is the goal state of
    _del_shmem — releasing it must not raise."""
    client = _bare_client()
    client._shmem = _VanishedSegment()
    client._del_shmem()
    assert client._shmem is None


@pytest.mark.unit
def test_del_shmem_without_segment_is_a_noop():
    client = _bare_client()
    client._del_shmem()
    assert client._shmem is None


@pytest.mark.unit
def test_extract_centroids_falls_back_when_segment_vanishes(caplog):
    """The RemoveIPC scenario end to end: the shmem RPC fails INTERNAL,
    the (externally unlinked) segment is released without an exception,
    and the same call retries with the image inlined in the request —
    so the frame that hits the error still gets centroids."""
    client = _bare_client()

    calls = []

    def fake_extract(req):
        calls.append(req)
        if len(calls) == 1:
            raise _InternalRpcError()
        return types.SimpleNamespace(star_candidates=[])

    client._stub = types.SimpleNamespace(ExtractCentroids=fake_extract)

    image = np.zeros((32, 32), dtype=np.uint8)
    try:
        # Let the client create its real segment, then delete its name
        # out from under it, exactly as logind's RemoveIPC does.
        client._alloc_shmem(size=image.size)
        vanish = shared_memory.SharedMemory(client._shmem.name)
        vanish.close()
        vanish.unlink()

        with caplog.at_level(logging.WARNING, logger="Solver"):
            centroids = client.extract_centroids(
                image, sigma=8, max_size=10, use_binned=True
            )
    finally:
        # The segment name is gone; make teardown tolerant either way.
        try:
            client._del_shmem()
        except Exception:
            pass

    assert centroids == []
    assert client._use_shmem is False
    assert client._shmem is None
    # First call went over shmem and failed; the retry carried the pixels.
    assert len(calls) == 2
    assert calls[1].input_image.image_data == image.tobytes()
    # ...and the retry keeps hot-pixel rejection on. The proto3 default is
    # false, so an omitted field would silently let hot pixels be detected as
    # stars for the rest of the run.
    assert calls[0].detect_hot_pixels is True
    assert calls[1].detect_hot_pixels is True
    # The downgrade is permanent for this process, so it has to be visible in
    # the logs -- otherwise the only symptom is a slower extract time.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "shared-memory handoff failed" in warnings[0].getMessage()
    assert _CEDAR_DETECT_SHMEM_NAME in warnings[0].getMessage()
