import json
import os
import struct
import urllib.error

import pytest

from PiFinder import delta_updates

pytestmark = pytest.mark.unit


TARGET = "/nix/store/1xm0hcqksxfy24p8m2xsfdas7wvyga76-testpkg-1.1"
BASE = "/nix/store/6jpbvvp1njd0h18knw1ddi1p2r29inh1-testpkg-1.0"


# --------------------------------------------------------------------------
# Naming helpers.


@pytest.mark.parametrize(
    "name,expected",
    [
        ("python3.13-numpy-2.1.3", "python3.13-numpy"),
        ("testpkg-1.0", "testpkg"),
        ("glibc-2.40-66", "glibc"),
        ("etc", "etc"),
        ("nixos-system-pifinder-25.11.20260209.2db38e0", "nixos-system-pifinder"),
        ("1", "1"),  # never strips down to nothing
    ],
)
def test_stem(name, expected):
    assert delta_updates.stem(name) == expected


def test_split_store_path():
    digest, name = delta_updates.split_store_path(TARGET)
    assert digest == "1xm0hcqksxfy24p8m2xsfdas7wvyga76"
    assert name == "testpkg-1.1"
    assert delta_updates.split_store_path("/nix/store/short-x") is None
    assert delta_updates.split_store_path("/nix/store/" + "A" * 32 + "-x") is None


def test_basis_candidates_prefers_newest(tmp_path):
    store = tmp_path
    old = store / (BASE.rsplit("/", 1)[1])
    new = store / ("qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq-testpkg-1.0.1")
    old.mkdir()
    new.mkdir()
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    index = delta_updates.local_store_index(store)
    cands = delta_updates.basis_candidates(TARGET, index)
    assert cands == [str(new), str(old)]


def test_basis_candidates_excludes_target_itself(tmp_path):
    (tmp_path / TARGET.rsplit("/", 1)[1]).mkdir()
    index = delta_updates.local_store_index(tmp_path)
    # The only same-stem path is the target: no candidates.
    assert (
        delta_updates.basis_candidates("/nix/store/" + TARGET.rsplit("/", 1)[1], index)
        == []
    )


def test_local_store_index_skips_drv_and_lock(tmp_path):
    (tmp_path / ("a" * 32 + "-foo-1.0.drv")).touch()
    (tmp_path / ("b" * 32 + "-foo-1.0.lock")).touch()
    assert delta_updates.local_store_index(tmp_path) == {}


# --------------------------------------------------------------------------
# Import-stream framing. Byte-exact: this is the nix-store --export wire
# format, and --import rejects any framing drift.


def _u64(n):
    return struct.pack("<Q", n)


def test_import_stream_parts_framing():
    prefix, suffix = delta_updates.import_stream_parts(
        "/nix/store/aaaa-x", ["/nix/store/bbbb-y"], "/nix/store/cccc-z.drv"
    )
    assert prefix == _u64(1)

    expected = _u64(0x4558494E)
    expected += _u64(17) + b"/nix/store/aaaa-x" + b"\x00" * 7
    expected += _u64(1)
    expected += _u64(17) + b"/nix/store/bbbb-y" + b"\x00" * 7
    expected += _u64(21) + b"/nix/store/cccc-z.drv" + b"\x00" * 3
    expected += _u64(0) + _u64(0)
    assert suffix == expected


def test_import_stream_no_deriver_sorted_refs():
    _, suffix = delta_updates.import_stream_parts(
        "/nix/store/aaaa-x", ["/nix/store/z-b", "/nix/store/a-a"], None
    )
    # References are serialized sorted; empty deriver is an empty string.
    a = suffix.find(b"/nix/store/a-a")
    z = suffix.find(b"/nix/store/z-b")
    assert 0 < a < z
    assert _u64(0) + _u64(0) == suffix[-16:]


def test_string_padding_multiple_of_eight():
    for length in range(1, 20):
        blob = delta_updates._string("x" * length)
        assert len(blob) % 8 == 0
        assert blob[:8] == _u64(length)


# --------------------------------------------------------------------------
# Server protocol.


class _FakeResp:
    def __init__(self, status, body=b"{}"):
        self.status = status
        self._body = body

    def read(self, *a):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_request_delta_hit(monkeypatch):
    payload = json.dumps({"url": "/blobs/x.zst"}).encode()

    monkeypatch.setenv("PIFINDER_DELTA_URL", "http://differ")
    monkeypatch.setattr(
        delta_updates.urllib.request,
        "urlopen",
        lambda req, timeout=None: _FakeResp(200, payload),
    )
    state, info = delta_updates.request_delta(TARGET, [BASE], "tok")
    assert state == "hit"
    assert info == {"url": "/blobs/x.zst"}


@pytest.mark.parametrize(
    "outcome,expected",
    [
        (202, "wait"),
        (204, "none"),
        (
            urllib.error.HTTPError("u", 500, "boom", None, None),
            "error",
        ),
        (urllib.error.URLError("down"), "error"),
    ],
)
def test_request_delta_non_hit(monkeypatch, outcome, expected):
    def _open(req, timeout=None):
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResp(outcome)

    monkeypatch.setenv("PIFINDER_DELTA_URL", "http://differ")
    monkeypatch.setattr(delta_updates.urllib.request, "urlopen", _open)
    state, _ = delta_updates.request_delta(TARGET, [BASE], "tok")
    assert state == expected


# --------------------------------------------------------------------------
# apply_delta guardrails (no subprocess reached).


def test_apply_delta_rejects_oversized_window(tmp_path, monkeypatch):
    monkeypatch.setenv("PIFINDER_DELTA_URL", "http://differ")
    info = {
        "basis": [BASE],
        "window_log": delta_updates.MAX_WINDOW_LOG + 1,
        "nar_sha256": "0" * 64,
        "nar_size": 10,
        "url": "/blobs/x.zst",
    }
    with pytest.raises(delta_updates.DeltaError, match="window"):
        delta_updates.apply_delta(TARGET, info, tmp_path)


def test_apply_delta_rejects_malformed_response(tmp_path, monkeypatch):
    monkeypatch.setenv("PIFINDER_DELTA_URL", "http://differ")
    with pytest.raises(delta_updates.DeltaError, match="malformed"):
        delta_updates.apply_delta(TARGET, {"basis": []}, tmp_path)


def test_apply_delta_rejects_missing_basis(tmp_path, monkeypatch):
    monkeypatch.setenv("PIFINDER_DELTA_URL", "http://differ")
    info = {
        "basis": ["/nix/store/" + "d" * 32 + "-gone-1.0"],
        "window_log": 27,
        "nar_sha256": "0" * 64,
        "nar_size": 10,
        "url": "/blobs/x.zst",
    }
    with pytest.raises(delta_updates.DeltaError, match="disappeared"):
        delta_updates.apply_delta(TARGET, info, tmp_path)


# --------------------------------------------------------------------------
# prefetch_deltas must never raise and must be inert when disabled.


def test_prefetch_disabled_without_env(monkeypatch):
    monkeypatch.delenv("PIFINDER_DELTA_URL", raising=False)
    assert delta_updates.prefetch_deltas(TARGET, (TARGET,)) == 0


def test_prefetch_never_raises(monkeypatch):
    monkeypatch.setenv("PIFINDER_DELTA_URL", "http://differ")

    def _boom(*a, **kw):
        raise RuntimeError("chaos")

    monkeypatch.setattr(delta_updates, "start_session", _boom)
    assert delta_updates.prefetch_deltas(TARGET, (TARGET,)) == 0


def test_prefetch_stops_without_session(monkeypatch):
    monkeypatch.setenv("PIFINDER_DELTA_URL", "http://differ")
    monkeypatch.setattr(delta_updates, "start_session", lambda t: None)

    def _no_requests(*a, **kw):
        raise AssertionError("no /delta request may happen without a session")

    monkeypatch.setattr(delta_updates, "request_delta", _no_requests)
    assert delta_updates.prefetch_deltas(TARGET, (TARGET,)) == 0


def test_start_session_parses_token(monkeypatch):
    payload = json.dumps({"session": "abc123", "budget": 100}).encode()
    monkeypatch.setenv("PIFINDER_DELTA_URL", "http://differ")
    captured = {}

    def _open(req, timeout=None):
        captured["url"] = req.full_url
        return _FakeResp(200, payload)

    monkeypatch.setattr(delta_updates.urllib.request, "urlopen", _open)
    assert delta_updates.start_session(TARGET) == "abc123"
    assert captured["url"].endswith("/update-start")


def test_start_session_none_on_failure(monkeypatch):
    monkeypatch.setenv("PIFINDER_DELTA_URL", "http://differ")

    def _open(req, timeout=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(delta_updates.urllib.request, "urlopen", _open)
    assert delta_updates.start_session(TARGET) is None


def test_request_delta_sends_session_header(monkeypatch):
    monkeypatch.setenv("PIFINDER_DELTA_URL", "http://differ")
    captured = {}

    def _open(req, timeout=None):
        captured["session"] = req.headers.get("X-update-session")
        return _FakeResp(200, b"{}")

    monkeypatch.setattr(delta_updates.urllib.request, "urlopen", _open)
    delta_updates.request_delta(TARGET, [BASE], "tok-1")
    assert captured["session"] == "tok-1"
