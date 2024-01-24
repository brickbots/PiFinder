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
