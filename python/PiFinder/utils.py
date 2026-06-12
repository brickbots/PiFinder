import os
import time
import logging
import json
from pathlib import Path
import importlib


home_dir = Path.home()
# Repo root, anchored on this file (python/PiFinder/utils.py) so paths
# resolve regardless of cwd. All other modules derive paths from here.
pifinder_dir = Path(__file__).resolve().parents[2]
assert (pifinder_dir / "astro_data").is_dir(), f"repo root not at {pifinder_dir}"
astro_data_dir = pifinder_dir / "astro_data"
tetra3_dir = pifinder_dir / "python/PiFinder/tetra3/tetra3"
data_dir = Path(Path.home(), "PiFinder_data")
pifinder_db = astro_data_dir / "pifinder_objects.db"
observations_db = data_dir / "observations.db"
debug_dump_dir = data_dir / "solver_debug_dumps"
comet_file = astro_data_dir / Path("comets.txt")


def create_dir(adir: str):
    create_path(Path(adir))


def create_path(apath: Path):
    os.makedirs(apath, exist_ok=True)


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
    # Check if we should use fake sys_utils for local development
    use_fake = os.environ.get("PIFINDER_USE_FAKE_SYS_UTILS", "").lower() in (
        "1",
        "true",
        "yes",
    )

    if use_fake:
        sys_utils = importlib.import_module("PiFinder.sys_utils_fake")
    else:
        try:
            # Attempt to import the real sys_utils
            sys_utils = importlib.import_module("PiFinder.sys_utils")
        except ImportError:
            sys_utils = importlib.import_module("PiFinder.sys_utils_fake")
    return sys_utils


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


def format_size_value(value):
    """
    Format a size value, removing unnecessary .0 decimals but preserving meaningful decimals.

    Examples:
        17.0 -> "17"
        17.5 -> "17.5"
        17.25 -> "17.3" (rounded to 1 decimal)
    """
    if value is None or value == "":
        return ""

    try:
        num_val = float(value)
        # If it's a whole number, return as integer
        if num_val == int(num_val):
            return str(int(num_val))
        # Otherwise, round to 1 decimal and remove trailing zeros
        formatted = f"{num_val:.1f}"
        return formatted.rstrip("0").rstrip(".")
    except (ValueError, TypeError):
        return str(value)  # Return as-is if not a number
