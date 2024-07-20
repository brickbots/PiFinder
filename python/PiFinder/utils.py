import os
import time
from pathlib import Path
from PiFinder.state import SharedStateObj


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


def sleep_for_framerate(shared_state: SharedStateObj, limit_framerate=True) -> bool:
    if shared_state.power_state() <= 0:
        time.sleep(0.5)
        return True
    elif limit_framerate:
        time.sleep(1 / 30)
    return False


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


def is_number(s):
    """Check if a string can be converted to a float"""
    if s is None:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False
