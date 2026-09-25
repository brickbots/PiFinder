import json
import os
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


NARINFO = f"""StorePath: {TARGET}
URL: nar/abc.nar.zst
Compression: zstd
FileHash: sha256:1111
FileSize: 123
NarHash: sha256:2222
NarSize: 456
References: 6jpbvvp1njd0h18knw1ddi1p2r29inh1-testpkg-1.0
Deriver: 3333-testpkg-1.1.drv
Sig: pifinder:abcd==
"""


def test_local_cache_narinfo_points_at_local_nar():
    out = delta_updates.local_cache_narinfo(NARINFO, TARGET, "x.nar")
    lines = out.splitlines()
    assert "URL: nar/x.nar" in lines
    assert "Compression: none" in lines
    assert not any(line.startswith(("FileHash", "FileSize")) for line in lines)
    # The signed fields stay exactly as served.
    for field in ("StorePath", "NarHash", "NarSize", "References", "Sig"):
        served = [x for x in NARINFO.splitlines() if x.startswith(field + ":")]
        assert served and served[0] in lines


def test_local_cache_narinfo_rejects_other_path():
    with pytest.raises(delta_updates.DeltaError, match="not"):
        delta_updates.local_cache_narinfo(NARINFO, BASE, "x.nar")


def test_local_cache_narinfo_rejects_unsigned():
    unsigned = "\n".join(x for x in NARINFO.splitlines() if not x.startswith("Sig:"))
    with pytest.raises(delta_updates.DeltaError, match="signature"):
        delta_updates.local_cache_narinfo(unsigned, TARGET, "x.nar")


def test_import_verified_uses_nix_copy_without_sig_bypass(tmp_path, monkeypatch):
    nar = tmp_path / "new.nar"
    nar.write_bytes(b"nar")
    seen = {}

    def _run(args, **kw):
        seen["args"] = args
        cache = args[args.index("--from") + 1][len("file://") :]
        seen["narinfo"] = (
            open(os.path.join(cache, "1xm0hcqksxfy24p8m2xsfdas7wvyga76.narinfo"))
            .read()
            .splitlines()
        )
        seen["nar"] = open(
            os.path.join(cache, "nar", "1xm0hcqksxfy24p8m2xsfdas7wvyga76.nar"), "rb"
        ).read()

        class _R:
            returncode = 0
            stderr = ""

        return _R()

    monkeypatch.setattr(delta_updates.subprocess, "run", _run)
    delta_updates.import_verified(TARGET, NARINFO, nar, tmp_path)
    assert seen["args"][:3] == ["nix", "copy", "--from"]
    assert seen["args"][-1] == TARGET
    assert "--no-check-sigs" not in seen["args"]
    assert "Sig: pifinder:abcd==" in seen["narinfo"]
    assert seen["nar"] == b"nar"
    assert not (tmp_path / "cache").exists()


def test_import_verified_raises_on_copy_failure(tmp_path, monkeypatch):
    nar = tmp_path / "new.nar"
    nar.write_bytes(b"nar")

    class _R:
        returncode = 1
        stderr = "lacks a valid signature"

    monkeypatch.setattr(delta_updates.subprocess, "run", lambda *a, **k: _R())
    with pytest.raises(delta_updates.DeltaError, match="valid signature"):
        delta_updates.import_verified(TARGET, NARINFO, nar, tmp_path)


def test_fetch_narinfo_tries_caches_in_order(monkeypatch):
    urls = []

    def _urlopen(url, timeout=None):
        urls.append(url)
        if "first" in url:
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        return _FakeResp(200, NARINFO.encode())

    monkeypatch.setattr(delta_updates.urllib.request, "urlopen", _urlopen)
    got = delta_updates.fetch_narinfo(TARGET, ("https://c/first", "https://c/second/"))
    assert got == NARINFO
    assert urls == [
        "https://c/first/1xm0hcqksxfy24p8m2xsfdas7wvyga76.narinfo",
        "https://c/second/1xm0hcqksxfy24p8m2xsfdas7wvyga76.narinfo",
    ]


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


def test_apply_delta_needs_signed_narinfo(tmp_path, monkeypatch):
    monkeypatch.setenv("PIFINDER_DELTA_URL", "http://differ")
    monkeypatch.setattr(delta_updates, "fetch_narinfo", lambda t, c: None)

    def _no_download(*a, **kw):
        raise AssertionError("no patch download without a signed narinfo")

    monkeypatch.setattr(delta_updates, "_download", _no_download)
    info = {
        "basis": [str(tmp_path)],
        "window_log": 27,
        "nar_sha256": "0" * 64,
        "nar_size": 10,
        "url": "/blobs/x.zst",
    }
    with pytest.raises(delta_updates.DeltaError, match="narinfo"):
        delta_updates.apply_delta(TARGET, info, tmp_path, caches=("https://c",))


def test_prefetch_disabled_without_env(monkeypatch):
    monkeypatch.delenv("PIFINDER_DELTA_URL", raising=False)
    assert delta_updates.prefetch_deltas(TARGET, (TARGET,), ("https://c",)) == 0


def test_prefetch_disabled_without_caches(monkeypatch):
    monkeypatch.setenv("PIFINDER_DELTA_URL", "http://differ")

    def _no_session(*a, **kw):
        raise AssertionError("no session without a narinfo source")

    monkeypatch.setattr(delta_updates, "start_session", _no_session)
    assert delta_updates.prefetch_deltas(TARGET, (TARGET,)) == 0


def test_prefetch_never_raises(monkeypatch):
    monkeypatch.setenv("PIFINDER_DELTA_URL", "http://differ")

    def _boom(*a, **kw):
        raise RuntimeError("chaos")

    monkeypatch.setattr(delta_updates, "start_session", _boom)
    assert delta_updates.prefetch_deltas(TARGET, (TARGET,), ("https://c",)) == 0


def test_prefetch_stops_without_session(monkeypatch):
    monkeypatch.setenv("PIFINDER_DELTA_URL", "http://differ")
    monkeypatch.setattr(delta_updates, "start_session", lambda t: None)

    def _no_requests(*a, **kw):
        raise AssertionError("no /delta request may happen without a session")

    monkeypatch.setattr(delta_updates, "request_delta", _no_requests)
    assert delta_updates.prefetch_deltas(TARGET, (TARGET,), ("https://c",)) == 0


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
