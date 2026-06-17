import os
import errno
import fcntl
import time
import logging
import json
from pathlib import Path
from typing import Optional
import importlib


home_dir = Path.home()
# Repo root, anchored on this file (python/PiFinder/utils.py) so paths
# resolve regardless of cwd. All other modules derive paths from here.
pifinder_dir = Path(__file__).resolve().parents[2]
assert (pifinder_dir / "astro_data").is_dir(), f"repo root not at {pifinder_dir}"
astro_data_dir = pifinder_dir / "astro_data"
tetra3_dir = pifinder_dir / "python/PiFinder/tetra3"
data_dir = Path(Path.home(), "PiFinder_data")
pifinder_db = astro_data_dir / "pifinder_objects.db"
observations_db = data_dir / "observations.db"
build_json = pifinder_dir / "pifinder-build.json"


def get_version() -> str:
    try:
        with open(build_json, "r") as f:
            return json.load(f).get("version", "Unknown")
    except (FileNotFoundError, IOError, json.JSONDecodeError):
        return "Unknown"


debug_dump_dir = data_dir / "solver_debug_dumps"
comet_file = data_dir / "comets.txt"


def create_dir(adir: str):
    create_path(Path(adir))


def create_path(apath: Path):
    os.makedirs(apath, exist_ok=True)


# Held open for the whole process lifetime: the flock lives on this open file
# description, so the kernel drops it the moment the process exits.
_instance_lock_file = None


def runtime_lock_dir() -> Optional[Path]:
    """RAM-backed dir for the single-instance lock, or None if none exists.

    Prefer /dev/shm (tmpfs on Linux/Raspberry Pi OS, already used for the cedar
    image buffer) so the lock never wears the SD card and is cleared on reboot.
    We deliberately do NOT fall back to the SD-card data dir: if no writable
    tmpfs is available we skip locking entirely (see
    :func:`acquire_single_instance_lock`) rather than wear the card.
    """
    shm = Path("/dev/shm")
    if shm.is_dir() and os.access(shm, os.W_OK):
        return shm
    return None


def acquire_single_instance_lock(
    lock_name: str = "pifinder.lock", lock_dir: Optional[Path] = None
) -> bool:
    """Best-effort guard so only one PiFinder runs at a time.

    Uses an advisory ``fcntl.flock`` on a tmpfs lock file (see
    :func:`runtime_lock_dir`), so it costs no SD-card writes. The kernel
    releases the lock when this process exits for ANY reason — clean shutdown,
    crash, ``kill -9``, or power loss — so an unclean stop never leaves a stale
    lock that blocks the next boot. A leftover lock *file* is harmless; only a
    live lock-holder blocks.

    The guard fails OPEN: it returns False (caller should not start) ONLY when
    another instance is confirmed to be holding the lock. Anything that breaks
    the locking mechanism itself — no tmpfs, an unopenable file, flock
    unsupported on the filesystem — is logged and treated as success, so a
    missing lock can never stop PiFinder from starting.
    """
    global _instance_lock_file
    log = logging.getLogger("utils")
    if lock_dir is None:
        lock_dir = runtime_lock_dir()
    if lock_dir is None:
        log.warning("No tmpfs lock dir available; starting without instance lock.")
        return True

    try:
        lock_file = open(lock_dir / lock_name, "a+")
    except OSError as e:
        log.warning("Could not open instance lock (%s); starting without it.", e)
        return True

    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
            # Held by a live process -> a genuine second instance.
            lock_file.seek(0)
            holder = lock_file.read().strip() or "unknown"
            lock_file.close()
            log.error(
                "Another PiFinder instance is already running (pid %s); not starting.",
                holder,
            )
            return False
        # Any other error means the lock mechanism is unavailable, not that a
        # duplicate is running -> fail open so startup is never hindered.
        log.warning("Instance lock unavailable (%s); starting without it.", e)
        lock_file.close()
        return True

    # Record our pid so a later blocked instance can name the holder.
    lock_file.seek(0)
    lock_file.truncate(0)
    lock_file.write(f"{os.getpid()}\n")
    lock_file.flush()
    _instance_lock_file = lock_file
    return True


def serialize_solution(solution) -> str:
    """
    Render a :class:`PointingEstimate` to a JSON string for observation
    logging. The output captures the published aligned-axis pointing,
    horizontal coords, source/timing, diagnostics, and the camera-axis
    solve cell.
    """
    from PiFinder.types.positioning import PointingEstimate

    if solution is None:
        return json.dumps({})

    if not isinstance(solution, PointingEstimate):
        # Defensive: if anything still passes a dict, emit it directly
        # so we don't crash. Strip non-JSON-friendly types like before.
        out_dict = {}
        for k, v in solution.items():
            if "uint16" in str(type(v)):
                v = int(v)
            if "numpy.float" in str(type(v)):
                v = float(v)
            if "quaternion" in str(type(v)):
                v = v.components.tolist()
            out_dict[k] = v
        return json.dumps(out_dict)

    aligned = solution.pointing.aligned.estimate
    camera_solve = solution.pointing.camera.solve
    imu_anchor = solution.imu_anchor
    out_dict = {
        "RA": aligned.RA if aligned else None,
        "Dec": aligned.Dec if aligned else None,
        "Roll": aligned.Roll if aligned else None,
        "Alt": solution.Alt,
        "Az": solution.Az,
        "camera_solve": {
            "RA": camera_solve.RA if camera_solve else None,
            "Dec": camera_solve.Dec if camera_solve else None,
            "Roll": camera_solve.Roll if camera_solve else None,
        },
        "imu_quat": imu_anchor.components.tolist() if imu_anchor else None,
        "solve_source": solution.solve_source.value if solution.solve_source else None,
        "estimate_time": solution.estimate_time,
        "last_solve_attempt": solution.last_solve_attempt,
        "last_solve_success": solution.last_solve_success,
        "constellation": solution.constellation,
        "Matches": solution.diagnostics.Matches,
        "RMSE": solution.diagnostics.RMSE,
        "Prob": solution.diagnostics.Prob,
        "FOV": solution.diagnostics.FOV,
        "T_solve": solution.diagnostics.T_solve,
        "T_extract": solution.diagnostics.T_extract,
    }
    return json.dumps(out_dict)


def get_sys_utils():
    try:
        return importlib.import_module("PiFinder.sys_utils")
    except Exception:
        return importlib.import_module("PiFinder.sys_utils_fake")


def get_os_info():
    import platform

    platform_system = platform.system()

    # Get the architecture (e.g., '64bit', 'ARM')
    architecture = platform.machine()

    # For more details, including the specific distribution on Linux
    if platform_system == "Linux":
        lib = "N/A"
        version = "N/A"
        libc_ver = (lib, version)
        try:
            libc_ver = platform.libc_ver(lib=lib, version=version)
        except AttributeError:
            pass
        os_detail = f"{platform_system} ({libc_ver[0]} {libc_ver[1]})"
    elif platform_system == "Darwin":
        os_detail = f"macOS ({platform.mac_ver()[0]})"
    elif platform_system == "Windows":
        os_detail = f"Windows ({platform.win32_ver()})"
    else:
        os_detail = "N/A"
    return os_detail, platform_system, architecture


class Timer:
    """
    Time multiple code blocks using a context manager.
    Usage:
        with Timer("deduplicate_objects 1"):
            results1 = deduplicate_objects(results*10)
        with Timer("deduplicate_objects 2"):
            results2 = deduplicate_objects(results*10)
    """

    def __init__(self, name):
        self.name = name
        self.start_time = None
        self.logger = logging.getLogger("Utils.Timer")

    def __enter__(self):
        self.start_time = time.time()

    def __exit__(self, exc_type, exc_value, traceback):
        end_time = time.time()
        elapsed_time = end_time - self.start_time
        self.logger.debug("%s: %.6f seconds", self.name, elapsed_time)


def is_number(s):
    """Check if a string can be converted to a float"""
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False
