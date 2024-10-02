import os
import time
import logging
from pathlib import Path
import importlib


def create_dir(adir: str):
    create_path(Path(adir))


def create_path(apath: Path):
    os.makedirs(apath, exist_ok=True)


home_dir = Path.home()
cwd_dir = Path.cwd()
pifinder_dir = Path("..")
astro_data_dir = pifinder_dir / "astro_data"
tetra3_dir = pifinder_dir / "python/PiFinder/tetra3/tetra3"
data_dir = Path(Path.home(), "PiFinder_data")
pifinder_db = astro_data_dir / "pifinder_objects.db"
observations_db = data_dir / "observations.db"
debug_dump_dir = data_dir / "solver_debug_dumps"
comet_file = astro_data_dir / Path("comets.txt")


def get_sys_utils():
    try:
        # Attempt to import the real sys_utils
        sys_utils = importlib.import_module('PiFinder.sys_utils')
    except ImportError:
        sys_utils = importlib.import_module('PiFinder.sys_utils_fake')
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
