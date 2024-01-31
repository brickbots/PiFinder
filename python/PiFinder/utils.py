import os
from pathlib import Path


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


def get_os_info():
    import platform

    platform_system = platform.system()

    # Get the architecture (e.g., '64bit', 'ARM')
    architecture = platform.machine()

    # For more details, including the specific distribution on Linux
    if platform_system == "Linux":
        try:
            # Only available on some Unix systems
            distribution = platform.linux_distribution()
        except AttributeError:
            # For Python 3.8 and above
            distribution = platform.dist()
        os_detail = f"{platform_system} ({distribution[0]} {distribution[1]})"
    elif platform_system == "Darwin":
        os_detail = f"macOS ({platform.mac_ver()[0]})"
    elif platform_system == "Windows":
        os_detail = f"Windows ({platform.version()})"
    else:
        os_detail = platform_system

    return os_detail, platform_system, architecture
