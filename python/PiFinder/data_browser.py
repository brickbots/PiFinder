"""File browser for the PiFinder data directory.

Backs the "Data" page of the web interface. It gives the same access as the
SMB share (``//pifinder.local/shared`` -> ``~/PiFinder_data``) to users who do
not want to set up SMB: list, upload, download and delete files and folders.

Every operation takes a path *relative to the data root* and refuses anything
that resolves outside that root (``..``, absolute paths, symlinks pointing
out). The root itself cannot be deleted.
"""

import fnmatch
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, BinaryIO, Optional

from PiFinder import utils


class DataPathError(ValueError):
    """A path is outside the data root, missing, or otherwise not usable."""


@dataclass(frozen=True)
class Shortcut:
    """A quick link to a well known folder inside the data root."""

    label: str
    path: str
    description: str
    pattern: str = ""  # optional glob; only matching entries are listed


# Folders that users most often want to reach. Only the ones that exist on
# the device are shown; see :func:`shortcuts`.
SHORTCUTS = (
    Shortcut("Observing lists", "obslists", "Lists you can load at the telescope"),
    Shortcut("Captures", "captures", "Images saved when you log an object"),
    Shortcut("SQM sweeps", "captures", "SQM sweep folders", "sweep_*"),
    Shortcut("SQM calibration", "calibration", "SQM calibration runs", "sqm_cal_*"),
    Shortcut("Screenshots", "screenshots", "Screenshots taken on the PiFinder"),
    Shortcut("Solver debug dumps", "solver_debug_dumps", "Solver debug images"),
    Shortcut("Logs", "logs", "Archived log files"),
)


def data_root() -> Path:
    """The directory exposed by the browser (same as the SMB share)."""
    return Path(utils.data_dir)


def resolve(root: Path, rel_path: str) -> Path:
    """Turn a user supplied relative path into a safe absolute path.

    Raises :class:`DataPathError` if the result is not inside ``root``.
    """
    rel_path = (rel_path or "").strip().lstrip("/")
    root_resolved = root.resolve()
    candidate = (root_resolved / rel_path).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        raise DataPathError("Path is outside the data directory")
    return candidate


def relative(root: Path, path: Path) -> str:
    """The forward-slash relative path of ``path`` under ``root``."""
    rel = path.resolve().relative_to(root.resolve())
    return rel.as_posix() if rel.parts else ""


def _entry(root: Path, path: Path) -> dict[str, Any]:
    st = path.lstat()
    is_dir = path.is_dir()
    return {
        "name": path.name,
        "path": relative(root, path),
        "is_dir": is_dir,
        "is_text": (not is_dir) and is_text_file(path.name),
        "size": None if is_dir else st.st_size,
        "mtime": int(st.st_mtime),
    }


def list_dir(root: Path, rel_path: str = "", pattern: str = "") -> dict[str, Any]:
    """List one folder. Folders come first, then files, both sorted by name.

    ``pattern`` is an optional glob (``sweep_*``); when set, only matching
    names are returned.
    """
    target = resolve(root, rel_path)
    if not target.is_dir():
        raise DataPathError("Folder not found")
    entries = []
    for child in target.iterdir():
        if pattern and not fnmatch.fnmatch(child.name, pattern):
            continue
        try:
            entries.append(_entry(root, child))
        except OSError:
            continue
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    rel = relative(root, target)
    crumbs = []
    acc = ""
    for part in Path(rel).parts:
        acc = f"{acc}/{part}" if acc else part
        crumbs.append({"name": part, "path": acc})
    return {
        "path": rel,
        "parent": relative(root, target.parent) if rel else None,
        "breadcrumbs": crumbs,
        "pattern": pattern,
        "entries": entries,
    }


def shortcuts(root: Path) -> list[dict[str, Any]]:
    """Shortcuts whose folder exists on this device."""
    out = []
    for sc in SHORTCUTS:
        try:
            if resolve(root, sc.path).is_dir():
                out.append(asdict(sc))
        except DataPathError:
            continue
    return out


def make_dir(root: Path, rel_path: str, name: str) -> str:
    """Create a folder ``name`` inside ``rel_path``; returns its relative path."""
    name = _clean_name(name)
    target = resolve(root, f"{rel_path}/{name}")
    if target.exists():
        raise DataPathError("A file or folder with that name already exists")
    target.mkdir(parents=False)
    return relative(root, target)


def save_upload(root: Path, rel_path: str, filename: str, stream: BinaryIO) -> str:
    """Save an uploaded file into ``rel_path``. Overwrites an existing file."""
    name = _clean_name(filename)
    folder = resolve(root, rel_path)
    if not folder.is_dir():
        raise DataPathError("Folder not found")
    target = folder / name
    if target.is_dir():
        raise DataPathError("A folder with that name already exists")
    with open(target, "wb") as f:
        shutil.copyfileobj(stream, f)
    return relative(root, target)


def delete(root: Path, rel_path: str) -> None:
    """Delete a file, or a folder and all of its contents."""
    target = resolve(root, rel_path)
    if target == root.resolve():
        raise DataPathError("The data directory itself cannot be deleted")
    if not target.exists() and not target.is_symlink():
        raise DataPathError("File or folder not found")
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
    else:
        target.unlink()


def zip_dir(root: Path, rel_path: str) -> tuple[BinaryIO, str]:
    """Zip a folder into an unlinked temp file.

    Returns an open, rewound file object and a download file name. The file
    is already unlinked, so closing the handle frees the space.
    """
    target = resolve(root, rel_path)
    if not target.is_dir():
        raise DataPathError("Folder not found")
    tmp = tempfile.TemporaryFile(suffix=".zip")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirs, files in os.walk(target):
            for fname in files:
                full = Path(dirpath) / fname
                if full.is_file():
                    zf.write(full, full.relative_to(target).as_posix())
    tmp.seek(0)
    name = target.name if target != root.resolve() else "PiFinder_data"
    return tmp, f"{name}.zip"


def file_for_download(root: Path, rel_path: str) -> Path:
    """Resolve a file path for download; raises if it is not a regular file."""
    target = resolve(root, rel_path)
    if not target.is_file():
        raise DataPathError("File not found")
    return target


TEXT_SUFFIXES = {
    ".txt",
    ".json",
    ".csv",
    ".tsv",
    ".log",
    ".md",
    ".ini",
    ".cfg",
    ".conf",
    ".yaml",
    ".yml",
    ".xml",
    ".py",
    ".sh",
    ".toml",
    ".dat",
    ".prof",
}
TEXT_VIEW_LIMIT = 1_000_000  # bytes shown in the viewer


def is_text_file(name: str) -> bool:
    """True for file names the web viewer can show as text."""
    return Path(name).suffix.lower() in TEXT_SUFFIXES


def read_text(
    root: Path, rel_path: str, limit: int = TEXT_VIEW_LIMIT
) -> dict[str, Any]:
    """Read up to ``limit`` bytes of a text file for the viewer.

    Returns ``{"text", "size", "truncated"}``. Undecodable bytes are replaced.
    """
    target = file_for_download(root, rel_path)
    size = target.stat().st_size
    with open(target, "rb") as f:
        data = f.read(limit)
    return {
        "text": data.decode("utf-8", errors="replace"),
        "size": size,
        "truncated": size > limit,
    }


def _clean_name(name: Optional[str]) -> str:
    """Reduce an uploaded/entered name to a single safe path component."""
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    if name in ("", ".", ".."):
        raise DataPathError("Invalid name")
    return name
