import os
from pathlib import Path


def create_dir(adir: str):
    create_path(Path(adir))


def create_path(apath: Path):
    os.makedirs(apath, exist_ok=True)


home_dir = Path.home()
cwd_dir = Path.cwd()
pifinder_dir = Path.home() / "PiFinder"
astro_data_dir = pifinder_dir / "astro_data"
data_dir = Path(Path.home(), "PiFinder_data")
pifinder_db = astro_data_dir / "pifinder_objects.db"
observations_db = data_dir / "observations.db"
debug_dump_dir = data_dir / "solver_debug_dumps"
