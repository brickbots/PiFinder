"""NixOS upgrade runner for PiFinder.

This module is intentionally small and standard-library only. It is launched by
systemd as root, writes the status file consumed by the UI, and guarantees a
terminal status for every non-reboot exit.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("PiFinder.nixos_upgrade")

RUN_DIR = Path("/run/pifinder")
UPGRADE_REF_FILE = RUN_DIR / "upgrade-ref"
UPGRADE_SELECTION_FILE = RUN_DIR / "upgrade-selection.json"
UPGRADE_STATUS_FILE = RUN_DIR / "upgrade-status"
UPGRADE_LOG_FILE = RUN_DIR / "upgrade-nix.log"
CURRENT_BUILD_FILE = Path("/var/lib/pifinder/current-build.json")
CAMERA_TYPE_FILE = Path("/var/lib/pifinder/camera-type")
# Arms pifinder-watchdog: present = the next boot is a trial of an unproven
# generation (roll back on failure); absent = committed system, never touched.
TRIAL_MARKER_FILE = Path("/var/lib/pifinder/trial-generation.json")

RELEASE_CACHE = "https://cache.pifinder.eu/pifinder-release"
DEV_CACHE = "https://cache.pifinder.eu/pifinder"
CACHES = (DEV_CACHE, RELEASE_CACHE)

STORE_PATH_RE = re.compile(r"/nix/store/[a-z0-9]+-[A-Za-z0-9._+=?,-]+")

# nix's --dry-run prints e.g. "(0.0 KiB download, 894.9 MiB unpacked)". Attic
# narinfos carry no compressed FileSize, so the unpacked figure is the only
# whole-download size nix can report; we use it as the progress denominator.
_UNPACKED_RE = re.compile(r"([\d.]+)\s+(B|KiB|MiB|GiB|TiB)\s+unpacked")
_SIZE_UNITS = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4}


def parse_unpacked_total(dry_output: str) -> int:
    m = _UNPACKED_RE.search(dry_output)
    if not m:
        return 0
    return int(float(m.group(1)) * _SIZE_UNITS[m.group(2)])


class UpgradeError(RuntimeError):
    """Generic upgrade failure."""


class UnavailableError(UpgradeError):
    """Selected store path is no longer available from configured caches."""


@dataclass(frozen=True)
class ProgressEvent:
    action: str
    activity_id: int
    activity_type: int | None
    path: str | None
    done: int | None = None
    expected: int | None = None


@dataclass(frozen=True)
class DownloadEstimate:
    paths: tuple[str, ...]
    # nix's dry-run "unpacked" byte total (0 if unknown). Per-path byte progress
    # streams live from the build's internal-json, so we keep no size map here.
    total_bytes: int = 0

    @property
    def path_count(self) -> int:
        return len(self.paths)


def write_status(status: str, status_file: Path = UPGRADE_STATUS_FILE) -> None:
    status_file.parent.mkdir(parents=True, exist_ok=True)
    status_file.write_text(status)


def valid_store_path(ref: str) -> bool:
    return bool(STORE_PATH_RE.fullmatch(ref))


def parse_store_paths(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(STORE_PATH_RE.findall(text)))


def parse_progress_event(line: str) -> ProgressEvent | None:
    if not line.startswith("@nix "):
        return None
    try:
        payload = json.loads(line[5:])
    except json.JSONDecodeError:
        return None

    action = payload.get("action")
    activity_id = payload.get("id")
    if not isinstance(activity_id, int):
        return None

    # resProgress (type 105): fields = [done, expected, running, failed]. Used
    # for smooth within-path byte progress (summed over copyPath activities).
    if action == "result" and payload.get("type") == 105:
        fields = payload.get("fields")
        if (
            isinstance(fields, list)
            and len(fields) >= 2
            and isinstance(fields[0], int)
            and isinstance(fields[1], int)
        ):
            return ProgressEvent(
                "result", activity_id, None, None, fields[0], fields[1]
            )
        return None

    if action not in ("start", "stop"):
        return None

    activity_type = payload.get("type")
    if activity_type is not None and not isinstance(activity_type, int):
        activity_type = None

    path = None
    for value in payload.values():
        if isinstance(value, str):
            match = STORE_PATH_RE.search(value)
            if match:
                path = match.group(0)
                break

    return ProgressEvent(action, activity_id, activity_type, path)


def command(
    args: list[str],
    *,
    check: bool = True,
    timeout: int | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise UpgradeError(
            f"{args[0]} failed rc={result.returncode}: {result.stderr.strip()}"
        )
    return result


def path_exists(path: str) -> bool:
    return Path(path).exists()


# Availability of a build on the binary caches, kept distinct on purpose: a
# cache we cannot reach must never be reported as "the build is gone".
AVAILABLE = "available"
ABSENT = "absent"
UNREACHABLE = "unreachable"


def _narinfo_url(store_path: str, cache: str) -> str:
    digest = Path(store_path).name.split("-", 1)[0]
    return f"{cache.rstrip('/')}/{digest}.narinfo"


def classify_store_path(
    store_path: str, caches: Iterable[str] = CACHES, timeout: int = 15
) -> str:
    """Decide whether a build is downloadable, gone, or simply unreachable.

    Probes each cache's narinfo over HTTPS so a network failure is never
    mistaken for a deleted build:
      - AVAILABLE    already in the local store, or a cache serves the narinfo
      - ABSENT       every cache answered and at least one returned 404 — the
                     build really is gone
      - UNREACHABLE  no cache could be reached (offline / DNS / cache down), so
                     availability is unknown and the upgrade should be retried
    """
    if path_exists(store_path):
        return AVAILABLE

    saw_404 = False
    unreachable = False
    for cache in caches:
        url = _narinfo_url(store_path, cache)
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                if resp.status == 200:
                    return AVAILABLE
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                saw_404 = True
            else:
                # 5xx and friends mean a troubled cache, not a deleted build.
                unreachable = True
        except (urllib.error.URLError, OSError, TimeoutError):
            unreachable = True

    if unreachable:
        return UNREACHABLE
    return ABSENT if saw_404 else UNREACHABLE


def fetch_cache_public_keys(
    caches: Iterable[str] = CACHES, timeout: int = 15
) -> list[str]:
    """Fetch each cache's current signing key from its anonymous Attic
    cache-config endpoint, so the upgrade trusts whatever key the cache uses
    *now*. This makes a cache signing-key rotation invisible to devices — they
    can never be stranded by a key change — while signature verification stays
    on (verified against the freshly-fetched key, over the same HTTPS trust
    boundary as the cache we already pull from). Best-effort: a cache we cannot
    reach contributes no key and we fall back to the device's configured keys.
    """
    keys: list[str] = []
    for cache in caches:
        base, _, name = cache.rstrip("/").rpartition("/")
        url = f"{base}/_api/v1/cache-config/{name}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                key = json.load(resp).get("public_key")
            if key:
                keys.append(key)
        except Exception as exc:  # network / JSON errors are non-fatal
            logger.warning("could not fetch cache key from %s: %s", url, exc)
    return keys


def estimate_download(store_path: str) -> DownloadEstimate:
    """Best-effort delta estimate: which paths nix will fetch, plus nix's own
    "unpacked" byte total from a dry-run. We deliberately do NOT query per-path
    sizes — the real byte progress streams live from the build's internal-json.
    An empty estimate must never block the actual build.
    """
    try:
        dry_result = command(
            ["nix-store", "--realise", "--dry-run", store_path],
            check=False,
            timeout=120,
        )
        dry = f"{dry_result.stdout}\n{dry_result.stderr}"
    except (subprocess.TimeoutExpired, OSError):
        return DownloadEstimate(())
    return DownloadEstimate(parse_store_paths(dry), parse_unpacked_total(dry))


def _short_pkg(path: str | None) -> str:
    """A screen-friendly package name from a store path: drop the
    /nix/store/<hash>- prefix and trim, e.g.
    '/nix/store/xxx-python3-3.13.11' -> 'python3-3.13.11'."""
    if not path:
        return ""
    return path.rsplit("/", 1)[-1].split("-", 1)[-1][:22]


class _DownloadProgress:
    """Best-effort download progress from nix's internal-json stream.

    Numerator = running sum of bytes copied across copyPath activities (their
    resProgress events); denominator = nix's dry-run "unpacked" total. So the
    bar moves *within* a path, not only when one finishes — and it names the
    package being copied. Status writes are throttled (the stream emits hundreds
    of thousands of events). Best-effort throughout: run_build wraps feed() so a
    bug here can never abort the upgrade.
    """

    def __init__(self, total_bytes: int, total_paths: int, status_file: Path):
        self.total_bytes = total_bytes
        self.use_bytes = total_bytes > 0
        self.total_paths = total_paths
        self.status_file = status_file
        self._active: dict[int, str] = {}  # copyPath id -> short label
        self._done: dict[int, int] = {}  # copyPath id -> bytes copied
        self._expected: dict[int, int] = {}  # copyPath id -> expected bytes
        self._bytes = 0
        self._paths_seen = 0
        self._paths_done = 0
        self._label = ""
        self._last_written = -1
        # Only rewrite the status file every ~0.5% of the total (or 1 MiB).
        self._step = max(1 << 20, total_bytes // 200) if self.use_bytes else 0

    def feed(self, line: str) -> None:
        event = parse_progress_event(line)
        if event is None:
            return
        if event.action == "result":
            self._on_progress(event)
        elif event.activity_type == 100:
            if event.action == "start":
                self._on_start(event)
            elif event.action == "stop":
                self._on_stop(event)

    def _on_start(self, event: ProgressEvent) -> None:
        self._active[event.activity_id] = _short_pkg(event.path)
        self._paths_seen += 1
        self._label = self._active[event.activity_id] or self._label
        if not self.use_bytes:
            self._write_paths()

    def _on_progress(self, event: ProgressEvent) -> None:
        aid = event.activity_id
        if aid not in self._active:  # only copyPath activities we track
            return
        self._bytes += (event.done or 0) - self._done.get(aid, 0)
        self._done[aid] = event.done or 0
        if event.expected:
            self._expected[aid] = event.expected
        if self.use_bytes:
            pct = min(self._bytes, self.total_bytes)
            if pct - self._last_written >= self._step:
                self._write_bytes()

    def _on_stop(self, event: ProgressEvent) -> None:
        aid = event.activity_id
        if aid not in self._active:
            return
        label = self._active.pop(aid)
        self._paths_done += 1
        if self.use_bytes:
            full = self._expected.get(aid, self._done.get(aid, 0))
            self._bytes += full - self._done.get(aid, 0)
            self._done[aid] = full
            # show something still in flight, else the path that just finished
            self._label = next(iter(self._active.values()), label) or self._label
            self._write_bytes()
        else:
            self._write_paths()

    def _write_bytes(self) -> None:
        pct = min(self._bytes, self.total_bytes)
        self._last_written = pct
        msg = f"downloading {pct}/{self.total_bytes}"
        if self._label:
            msg += f" {self._label}"
        write_status(msg, self.status_file)

    def _write_paths(self) -> None:
        denom = self.total_paths or self._paths_seen
        write_status(f"downloading {self._paths_done}/{denom} paths", self.status_file)


def run_build(
    store_path: str,
    estimate: DownloadEstimate,
    *,
    status_file: Path = UPGRADE_STATUS_FILE,
    log_file: Path = UPGRADE_LOG_FILE,
) -> int:
    if estimate.total_bytes > 0:
        write_status(f"downloading 0/{estimate.total_bytes}", status_file)
    else:
        write_status(f"downloading 0/{estimate.path_count} paths", status_file)

    # Trust the cache's current signing key(s), fetched from the cache itself,
    # so a key rotation can never strand this device mid-upgrade. This ADDS to
    # the trusted set (verification stays on) — it is not a require-sigs bypass.
    build_args = [
        "nix",
        "--log-format",
        "internal-json",
        "build",
        store_path,
        "--max-jobs",
        "0",
        "--no-link",
    ]
    cache_keys = fetch_cache_public_keys()
    if cache_keys:
        build_args += ["--option", "extra-trusted-public-keys", " ".join(cache_keys)]

    progress = _DownloadProgress(estimate.total_bytes, estimate.path_count, status_file)
    tail: deque[str] = deque(maxlen=40)

    process = subprocess.Popen(
        build_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert process.stdout is not None
    for line in process.stdout:
        tail.append(line.rstrip())
        # Progress is a nice-to-have: never let an accounting bug stall the
        # stream (which would deadlock the build) or abort the upgrade.
        try:
            progress.feed(line)
        except Exception:
            logger.debug("progress tracking error", exc_info=True)
    return_code = process.wait()

    # Persist only a short tail for diagnostics — not the ~800k-line stream.
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("\n".join(tail) + "\n")
    except OSError:
        logger.debug("could not write upgrade log tail", exc_info=True)

    if return_code != 0:
        logger.error("nix build failed rc=%s; tail=%s", return_code, list(tail))
    return return_code


def load_selection(selection_file: Path = UPGRADE_SELECTION_FILE) -> dict:
    try:
        with selection_file.open() as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        pass
    return {}


def persist_current_build(store_path: str, selection: dict) -> None:
    CURRENT_BUILD_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "store_path": store_path,
        "version": selection.get("version") or selection.get("label") or store_path,
        "label": selection.get("label"),
        "channel": selection.get("channel"),
    }
    CURRENT_BUILD_FILE.write_text(json.dumps(data, sort_keys=True) + "\n")


def arm_trial_marker(boot_target: Path) -> None:
    """Arm the boot-health watchdog for the next boot.

    Records the currently-running (known-good) system and the generation the
    next boot is expected to run, so pifinder-watchdog can roll back if that
    generation fails its first boot. The watchdog deletes the marker once the
    new generation proves healthy (commit); no marker means a committed
    system, which is never auto-rolled-back.

    Best-effort: a marker failure must not block the upgrade — it only means
    this upgrade proceeds without the automatic safety net.
    """
    try:
        previous = Path("/run/current-system").resolve()
        new = boot_target.resolve()
        TRIAL_MARKER_FILE.parent.mkdir(parents=True, exist_ok=True)
        TRIAL_MARKER_FILE.write_text(
            json.dumps({"previous": str(previous), "new": str(new)}, sort_keys=True)
            + "\n"
        )
    except OSError as exc:
        logger.warning("could not arm trial marker: %s", exc)


def activate_system(store_path: str, default_camera: str) -> None:
    write_status("activating")
    command(["nix-env", "-p", "/nix/var/nix/profiles/system", "--set", store_path])

    try:
        camera = CAMERA_TYPE_FILE.read_text().strip()
    except OSError:
        camera = default_camera

    # Whether the chosen camera boots via a specialisation entry is a property
    # of the NEW build, so ask the new store path — never compare against
    # --default-camera, which is the RUNNING generation's base camera. When the
    # two builds disagree about the base (e.g. an imx477-base device upgrading
    # onto an imx462-base build), that comparison concludes "camera is the
    # base, nothing to do" and reboots into the wrong DTB, killing the camera.
    specialisation = Path(store_path) / "specialisation" / camera if camera else None
    if specialisation is not None and specialisation.is_dir():
        # The specialisation has its own toplevel — arm the watchdog with
        # what will actually be running after reboot.
        arm_trial_marker(specialisation)
        command([str(specialisation / "bin/switch-to-configuration"), "boot"])
        set_extlinux_default(camera, store_path)
        return

    arm_trial_marker(Path(store_path))
    command([str(Path(store_path) / "bin/switch-to-configuration"), "boot"])
    set_extlinux_default(camera or default_camera, store_path)


def set_extlinux_default(camera: str, store_path: str | None = None) -> None:
    """Point the extlinux DEFAULT at the selected camera's boot entry.

    Device-tree overlays load only at boot, and the generic-extlinux builder
    rewrites DEFAULT to the base camera on every activation — so without this an
    upgrade would reboot into the base camera's DTB regardless of the device's
    chosen camera. Best-effort: the helper leaves a bootable DEFAULT in place if
    the entry is missing, so a hiccup here never blocks the upgrade.

    The helper maps camera name -> boot entry using its build's own base-camera
    constant, so it must come from the NEW store path when available: the
    running generation's copy applies the OLD base mapping to the NEW entries
    and picks the wrong one whenever the two builds' base cameras differ.
    """
    helper = "set-extlinux-default"
    if store_path:
        candidate = Path(store_path) / "sw/bin/set-extlinux-default"
        if candidate.exists():
            helper = str(candidate)
    command([helper, camera], check=False)


def cleanup_old_generations() -> None:
    # Keep the 3 newest generations: current + 2 rollback targets (surfaced in
    # the Software screen's Rollback channel).
    command(
        ["nix-env", "--delete-generations", "+3", "-p", "/nix/var/nix/profiles/system"],
        check=False,
    )
    command(["nix-collect-garbage"], check=False)


def run_upgrade(ref_file: Path, default_camera: str) -> int:
    terminal = False
    selected_unavailable = False
    try:
        write_status("starting")
        store_path = ref_file.read_text().strip()
        if not valid_store_path(store_path):
            raise UpgradeError(f"invalid store path: {store_path!r}")

        estimate = estimate_download(store_path)
        build_rc = run_build(store_path, estimate)
        if build_rc != 0:
            availability = classify_store_path(store_path)
            if availability == ABSENT:
                selected_unavailable = True
                write_status("unavailable")
                terminal = True
                raise UnavailableError(
                    f"{store_path} is no longer on configured caches"
                )
            if availability == UNREACHABLE:
                # Couldn't reach the caches to download — a connection problem,
                # not a missing build. Retryable, so don't claim it's gone.
                write_status("connfail")
                terminal = True
                raise UpgradeError(f"caches unreachable for {store_path}")
            raise UpgradeError(f"nix build failed rc={build_rc}")

        selection = load_selection()
        activate_system(store_path, default_camera)
        persist_current_build(store_path, selection)
        cleanup_old_generations()
        write_status("rebooting")
        command(["systemctl", "reboot"])
        terminal = True
        return 0
    except UnavailableError:
        return 1
    except Exception as exc:
        logger.exception("upgrade failed: %s", exc)
        if not terminal and not selected_unavailable:
            write_status("failed")
        return 1


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref-file", type=Path, default=UPGRADE_REF_FILE)
    parser.add_argument("--default-camera", default="imx462")
    args = parser.parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(level=logging.INFO)
    return run_upgrade(args.ref_file, args.default_camera)


if __name__ == "__main__":
    raise SystemExit(main())
