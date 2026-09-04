"""Delta prefetch for NixOS upgrades.

Before nixos_upgrade lets nix download whole store paths, this module asks the
delta server for byte-level patches against store paths the device already
holds (any retained generation), applies them, and imports the results into
the store. Everything it manages to import is a path nix no longer downloads.

Protocol (server: pifinder-differ):
    POST {url}/update-start {"target_toplevel": "/nix/store/..."}
      200  {"session", "budget", "expires_in"}  per-update request budget,
           sized by the server from the target closure. The session token
           rides an x-update-session header on every later request.
    POST {url}/delta {"target": "/nix/store/...", "bases": ["/nix/store/..."]}
      200  {"url", "size", "window_log", "nar_sha256", "references",
            "deriver", "basis": [...]}          patch ready
      202  computing — retry after a short wait
      204  no basis worth using — full download
    GET  {url}{blob url}                        the patch bytes

A patch reconstructs the target's NAR from the base's NAR (`nix-store --dump`
on both ends is canonical, so the server and the device see identical base
bytes). The reconstructed NAR is verified against nar_sha256 BEFORE import —
`nix-store --import` does not check the NAR against the store path name for
input-addressed paths, so this line is what stands between a bad patch and a
corrupt store. Import framing (references, deriver) is assembled locally from
the /delta response.

Best-effort throughout: every failure path leaves the work to the binary
cache. Disabled unless PIFINDER_DELTA_URL is set (wired through the
pifinder.deltaUrl NixOS option).

Standard-library only, like nixos_upgrade.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger("PiFinder.delta_updates")

STORE_DIR = Path("/nix/store")

# One retry cycle on a 202: the server is computing a miss. Pre-warmed pairs
# answer 200 immediately; a genuinely cold pair is not worth stalling the
# upgrade for, so after RETRIES the path falls back to a normal download.
REQUEST_TIMEOUT = 20
RETRY_WAIT = 15
RETRIES = 2

# Candidate bases sent per target. More candidates cost bytes and server
# ranking time and rarely beat the newest same-stem path.
MAX_CANDIDATES = 3

# Decode memory is 2^window_log bytes. 28 = 256 MiB, the most a Pi 4 should
# spend mid-upgrade; the server raises window_log with NAR size, so this also
# caps how large a patched path can be.
MAX_WINDOW_LOG = 28

# Applying needs base NAR + patch + reconstructed NAR on disk at once, plus
# slack for the rest of the upgrade.
FREE_SPACE_SLACK = 512 * 1024 * 1024


def enabled() -> bool:
    return bool(os.environ.get("PIFINDER_DELTA_URL"))


def _delta_url() -> str:
    return os.environ["PIFINDER_DELTA_URL"].rstrip("/")


# --------------------------------------------------------------------------
# Candidate selection: newest same-stem paths already in the store.


def stem(name: str) -> str:
    """Package name with trailing version-ish components dropped.

    "python3.13-numpy-2.1.3" -> "python3.13-numpy"
    """
    parts = name.split("-")
    while len(parts) > 1 and parts[-1][:1].isdigit():
        parts.pop()
    return "-".join(parts)


def split_store_path(path: str) -> tuple[str, str] | None:
    """ "/nix/store/<32hash>-name" -> (hash, name), or None."""
    base = os.path.basename(path)
    if len(base) < 34 or base[32] != "-":
        return None
    digest, name = base[:32], base[33:]
    if not all(c.islower() or c.isdigit() for c in digest) or not name:
        return None
    return digest, name


def local_store_index(store_dir: Path = STORE_DIR) -> dict[str, list[str]]:
    """stem -> store paths present locally, across all retained generations."""
    index: dict[str, list[str]] = {}
    try:
        entries = list(store_dir.iterdir())
    except OSError:
        return index
    for entry in entries:
        if entry.name.endswith((".drv", ".lock")):
            continue
        parts = split_store_path(str(entry))
        if parts is None:
            continue
        index.setdefault(stem(parts[1]), []).append(str(entry))
    return index


def basis_candidates(
    target: str, index: dict[str, list[str]], limit: int = MAX_CANDIDATES
) -> list[str]:
    """Local paths most likely to resemble `target`, best guess first.

    Newest first: the most recently created path of the same package is
    almost always the closest in content, and needs no version parsing.
    """
    parts = split_store_path(target)
    if parts is None:
        return []
    target_base = os.path.basename(target)
    hits = [
        p for p in index.get(stem(parts[1]), []) if os.path.basename(p) != target_base
    ]

    def _mtime(p: str) -> float:
        try:
            return Path(p).stat().st_mtime
        except OSError:
            return 0.0

    hits.sort(key=_mtime, reverse=True)
    return hits[:limit]


# --------------------------------------------------------------------------
# Server protocol.


def start_session(target_toplevel: str) -> str | None:
    """Open the per-update session. The server sizes the request budget from
    the target closure; without a session every later request is refused, so
    None disables the prefetch for this run."""
    body = json.dumps({"target_toplevel": target_toplevel}).encode()
    req = urllib.request.Request(
        f"{_delta_url()}/update-start",
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.load(resp).get("session") or None
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        logger.warning("update-start failed: %s", exc)
        return None


def request_delta(target: str, bases: list[str], session: str) -> tuple[str, dict]:
    """One POST /delta. Returns (state, info) with state one of
    "hit" (info = server response), "wait", "none", "error"."""
    body = json.dumps({"target": target, "bases": bases}).encode()
    req = urllib.request.Request(
        f"{_delta_url()}/delta",
        data=body,
        headers={
            "content-type": "application/json",
            "x-update-session": session,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            if resp.status == 200:
                return "hit", json.load(resp)
            if resp.status == 202:
                return "wait", {}
            return "none", {}
    except urllib.error.HTTPError as exc:
        if exc.code == 202:
            return "wait", {}
        if exc.code == 204:
            return "none", {}
        logger.warning("delta request for %s: HTTP %s", target, exc.code)
        return "error", {}
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        logger.warning("delta request for %s: %s", target, exc)
        return "error", {}


# --------------------------------------------------------------------------
# Import-stream framing.
#
# `nix-store --import` reads the `nix-store --export` wire format. We have the
# NAR (reconstructed by the patch) and the metadata (from /delta), so the
# framing is assembled here instead of shipped: per path a u64 1 marker, the
# NAR bytes, the magic 0x4558494e, the store path, the references, the deriver
# ("" if none) and a u64 0; a final u64 0 ends the stream. Strings are u64le
# length + bytes zero-padded to 8.

EXPORT_MAGIC = 0x4558494E


def _u64(n: int) -> bytes:
    return struct.pack("<Q", n)


def _string(s: str) -> bytes:
    raw = s.encode()
    pad = (8 - len(raw) % 8) % 8
    return _u64(len(raw)) + raw + b"\x00" * pad


def import_stream_parts(
    target: str, references: list[str], deriver: str | None
) -> tuple[bytes, bytes]:
    """(prefix, suffix) around the raw NAR bytes of a one-path import stream."""
    prefix = _u64(1)
    suffix = _u64(EXPORT_MAGIC)
    suffix += _string(target)
    suffix += _u64(len(references))
    for ref in sorted(references):
        suffix += _string(ref)
    suffix += _string(deriver or "")
    suffix += _u64(0)  # no legacy signature
    suffix += _u64(0)  # end of stream
    return prefix, suffix


def import_nar(
    target: str, nar_file: Path, references: list[str], deriver: str | None
) -> None:
    """Feed prefix + NAR + suffix to `nix-store --import` without holding the
    NAR in memory."""
    prefix, suffix = import_stream_parts(target, references, deriver)
    proc = subprocess.Popen(
        ["nix-store", "--import"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None
    try:
        proc.stdin.write(prefix)
        with nar_file.open("rb") as f:
            shutil.copyfileobj(f, proc.stdin, 1024 * 1024)
        proc.stdin.write(suffix)
        proc.stdin.close()
    except BrokenPipeError:
        pass
    _, err = proc.communicate(timeout=600)
    if proc.returncode != 0:
        raise DeltaError(f"nix-store --import failed: {err.decode().strip()}")


class DeltaError(RuntimeError):
    """A delta could not be applied; the path falls back to a download."""


# --------------------------------------------------------------------------
# Apply one patch.


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _download(url: str, dest: Path, session: str) -> None:
    req = urllib.request.Request(url, headers={"x-update-session": session})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        with dest.open("wb") as f:
            shutil.copyfileobj(resp, f, 1024 * 1024)


def apply_delta(target: str, info: dict, workdir: Path, session: str = "") -> None:
    """Reconstruct `target` from a local base plus the served patch, verify,
    and import. Raises DeltaError on any problem; never leaves a registered
    path unverified."""
    basis = info.get("basis") or []
    base = basis[0] if basis else None
    window_log = int(info.get("window_log") or 0)
    nar_sha256 = info.get("nar_sha256") or ""
    nar_size = int(info.get("nar_size") or 0)
    if not base or not nar_sha256 or not window_log:
        raise DeltaError(f"malformed delta response for {target}")
    if window_log > MAX_WINDOW_LOG:
        raise DeltaError(f"window 2^{window_log} exceeds device budget")
    if not Path(base).exists():
        raise DeltaError(f"basis {base} disappeared")

    free = shutil.disk_usage(workdir).free
    need = 2 * nar_size + int(info.get("size") or 0) + FREE_SPACE_SLACK
    if free < need:
        raise DeltaError(f"not enough free space ({free} < {need})")

    # A corrupt local base must not silently produce a corrupt target.
    verify = subprocess.run(
        ["nix-store", "--verify-path", base],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if verify.returncode != 0:
        raise DeltaError(f"basis {base} fails verification")

    patch = workdir / "patch.zst"
    base_nar = workdir / "base.nar"
    new_nar = workdir / "new.nar"
    try:
        _download(f"{_delta_url()}{info['url']}", patch, session)

        with base_nar.open("wb") as f:
            dump = subprocess.run(["nix-store", "--dump", base], stdout=f, timeout=600)
        if dump.returncode != 0:
            raise DeltaError(f"nix-store --dump {base} failed")

        unzstd = subprocess.run(
            [
                "zstd",
                "-dq",
                "--force",
                f"--long={window_log}",
                f"--patch-from={base_nar}",
                str(patch),
                "-o",
                str(new_nar),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if unzstd.returncode != 0:
            raise DeltaError(f"zstd failed: {unzstd.stderr.strip()}")

        # The line between a bad patch and a corrupt store.
        digest = _sha256(new_nar)
        if digest != nar_sha256:
            raise DeltaError(
                f"reconstructed NAR hash mismatch ({digest} != {nar_sha256})"
            )

        import_nar(
            target, new_nar, list(info.get("references") or []), info.get("deriver")
        )
    except (OSError, subprocess.TimeoutExpired, urllib.error.URLError) as exc:
        raise DeltaError(str(exc)) from exc
    finally:
        for tmp in (patch, base_nar, new_nar):
            try:
                tmp.unlink()
            except OSError:
                pass


# --------------------------------------------------------------------------
# The one entry point nixos_upgrade calls.


def prefetch_deltas(target_toplevel: str, paths: tuple[str, ...]) -> int:
    """Fill the local store from patches. Returns paths imported.

    Best-effort: any failure — server down, patch broken, disk full — just
    means that path substitutes from the binary cache as before. Must never
    raise.
    """
    if not enabled():
        return 0
    imported = 0
    try:
        session = start_session(target_toplevel)
        if session is None:
            return 0
        index = local_store_index()
        with tempfile.TemporaryDirectory(prefix="pifinder-delta.") as tmp:
            workdir = Path(tmp)
            waiting: list[tuple[str, list[str]]] = []
            for target in paths:
                if Path(target).exists():
                    continue
                bases = basis_candidates(target, index)
                if not bases:
                    continue
                state, info = request_delta(target, bases, session)
                if state == "hit":
                    try:
                        apply_delta(target, info, workdir, session)
                        imported += 1
                    except DeltaError as exc:
                        logger.warning("delta for %s failed: %s", target, exc)
                elif state == "wait":
                    waiting.append((target, bases))

            # One bounded retry pass for pairs the server was still computing.
            for _ in range(RETRIES):
                if not waiting:
                    break
                time.sleep(RETRY_WAIT)
                still: list[tuple[str, list[str]]] = []
                for target, bases in waiting:
                    state, info = request_delta(target, bases, session)
                    if state == "hit":
                        try:
                            apply_delta(target, info, workdir, session)
                            imported += 1
                        except DeltaError as exc:
                            logger.warning("delta for %s failed: %s", target, exc)
                    elif state == "wait":
                        still.append((target, bases))
                waiting = still
    except Exception as exc:  # noqa: BLE001 — must never break the upgrade
        logger.warning("delta prefetch aborted: %s", exc)
    if imported:
        logger.info("delta prefetch imported %d path(s)", imported)
    return imported
