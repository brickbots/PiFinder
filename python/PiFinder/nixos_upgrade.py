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
UPGRADE_SIZES_FILE = RUN_DIR / "upgrade-sizes"
CURRENT_BUILD_FILE = Path("/var/lib/pifinder/current-build.json")
CAMERA_TYPE_FILE = Path("/var/lib/pifinder/camera-type")

RELEASE_CACHE = "https://cache.pifinder.eu/pifinder-release"
DEV_CACHE = "https://cache.pifinder.eu/pifinder"
CACHES = (DEV_CACHE, RELEASE_CACHE)

STORE_PATH_RE = re.compile(r"/nix/store/[a-z0-9]+-[A-Za-z0-9._+=?,-]+")


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


@dataclass(frozen=True)
class DownloadEstimate:
    sizes: dict[str, int]
    paths: tuple[str, ...]

    @property
    def total_bytes(self) -> int:
        return sum(self.sizes.values())

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
    if action not in ("start", "stop") or not isinstance(activity_id, int):
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


def cache_has_path(store_path: str, cache: str, timeout: int = 20) -> bool:
    try:
        result = command(
            ["nix", "path-info", "--store", cache, store_path],
            check=False,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def store_path_available(store_path: str) -> bool:
    return path_exists(store_path) or any(cache_has_path(store_path, c) for c in CACHES)


def estimate_download(store_path: str) -> DownloadEstimate:
    """Best-effort delta estimate.

    The returned estimate may be empty. That must not block the real build.
    """
    try:
        dry_result = command(
            ["nix-store", "--realise", "--dry-run", store_path],
            check=False,
            timeout=120,
        )
        dry = f"{dry_result.stdout}\n{dry_result.stderr}"
    except (subprocess.TimeoutExpired, OSError):
        return DownloadEstimate({}, ())

    paths = parse_store_paths(dry)
    if not paths:
        return DownloadEstimate({}, ())

    sizes: dict[str, int] = {}
    for cache in CACHES:
        try:
            result = command(
                ["nix", "path-info", "--json", "--store", cache, *paths],
                check=False,
                timeout=60,
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        if result.returncode != 0 or not result.stdout.strip():
            continue
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            data = list(data.values())
        for item in data:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            if not isinstance(path, str) or path_exists(path):
                continue
            size = item.get("downloadSize") or item.get("narSize") or 0
            try:
                sizes[path] = int(size)
            except (TypeError, ValueError):
                sizes[path] = 0

    return DownloadEstimate(sizes, paths)


def write_sizes_file(estimate: DownloadEstimate, sizes_file: Path = UPGRADE_SIZES_FILE):
    sizes_file.parent.mkdir(parents=True, exist_ok=True)
    with sizes_file.open("w") as f:
        for path, size in sorted(estimate.sizes.items()):
            f.write(f"{path} {size}\n")


def run_build(
    store_path: str,
    estimate: DownloadEstimate,
    *,
    status_file: Path = UPGRADE_STATUS_FILE,
    log_file: Path = UPGRADE_LOG_FILE,
) -> int:
    total_bytes = estimate.total_bytes
    use_bytes = total_bytes > 0 and bool(estimate.sizes)
    total_paths = estimate.path_count
    if use_bytes:
        write_status(f"downloading 0/{total_bytes}", status_file)
    else:
        write_status(f"downloading 0/{total_paths} paths", status_file)

    pending: dict[int, str | None] = {}
    paths_seen = 0
    paths_done = 0
    bytes_done = 0
    tail: deque[str] = deque(maxlen=40)

    with log_file.open("w") as log:
        process = subprocess.Popen(
            [
                "nix",
                "--log-format",
                "internal-json",
                "build",
                store_path,
                "--max-jobs",
                "0",
                "--no-link",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert process.stdout is not None
        for line in process.stdout:
            log.write(line)
            log.flush()
            tail.append(line.rstrip())
            event = parse_progress_event(line)
            if event is None or event.activity_type != 100:
                continue
            if event.action == "start":
                pending[event.activity_id] = event.path
                paths_seen += 1
                if not use_bytes and total_paths == 0:
                    write_status(
                        f"downloading {paths_done}/{paths_seen} paths", status_file
                    )
            elif event.action == "stop" and event.activity_id in pending:
                path = pending.pop(event.activity_id)
                paths_done += 1
                if use_bytes:
                    bytes_done += estimate.sizes.get(path or "", 0)
                    pct_done = min(bytes_done, total_bytes)
                    write_status(f"downloading {pct_done}/{total_bytes}", status_file)
                else:
                    denom = total_paths or paths_seen
                    write_status(f"downloading {paths_done}/{denom} paths", status_file)
        return_code = process.wait()

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


def activate_system(store_path: str, default_camera: str) -> None:
    write_status("activating")
    command(["nix-env", "-p", "/nix/var/nix/profiles/system", "--set", store_path])

    try:
        camera = CAMERA_TYPE_FILE.read_text().strip()
    except OSError:
        camera = default_camera

    if camera and camera != default_camera:
        specialisation = Path(store_path) / "specialisation" / camera
        if specialisation.is_dir():
            command([str(specialisation / "bin/switch-to-configuration"), "boot"])
            return

    command([str(Path(store_path) / "bin/switch-to-configuration"), "boot"])


def cleanup_old_generations() -> None:
    command(
        ["nix-env", "--delete-generations", "+2", "-p", "/nix/var/nix/profiles/system"],
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
        write_sizes_file(estimate)

        build_rc = run_build(store_path, estimate)
        if build_rc != 0:
            if not store_path_available(store_path):
                selected_unavailable = True
                write_status("unavailable")
                terminal = True
                raise UnavailableError(
                    f"{store_path} is no longer on configured caches"
                )
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
