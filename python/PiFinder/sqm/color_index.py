"""
Hipparcos B-V colour indices for SQM colour correction.

The tetra3 catalog magnitude is Johnson V, but SQM measures flux in the sensor's
own passband. On a sensor without an IR-cut filter the near-IR leak over-fluxes
red stars, so the effective catalog magnitude is ``V - T*(B-V)`` (see
``camera_profiles.color_coefficient``). This module supplies the per-star B-V
keyed by HIP number (the ``matched_catID`` returned by tetra3 solves).

B-V is read from ``astro_data/hip_main.dat`` field 37 and cached as a compact
sorted ``.npz`` (~0.5 MB) so the ~1s fixed-width parse only happens once, the
same pattern ``plot.py`` uses for the Hipparcos DataFrame.
"""

import logging
from pathlib import Path
from typing import Optional

import numpy as np

from PiFinder import utils

logger = logging.getLogger("SQM.ColorIndex")

# Pipe-separated field indices in hip_main.dat
_HIP_FIELD = 1
_BV_FIELD = 37

_HIP_SORTED: Optional[np.ndarray] = None
_BV_SORTED: Optional[np.ndarray] = None


def _dat_path() -> Path:
    return Path(utils.astro_data_dir, "hip_main.dat")


def _cache_path() -> Path:
    return Path(utils.data_dir, "cache", "hip_bv.npz")


def _parse_dat(dat_path: Path):
    """Parse HIP -> B-V from hip_main.dat. Returns (hip_sorted, bv_sorted)."""
    hips = []
    bvs = []
    with open(dat_path) as f:
        for line in f:
            fields = line.split("|")
            if len(fields) <= _BV_FIELD:
                continue
            try:
                hip = int(fields[_HIP_FIELD])
            except ValueError:
                continue
            try:
                bv = float(fields[_BV_FIELD])
            except ValueError:
                continue  # blank/missing B-V (~0.1% of stars)
            hips.append(hip)
            bvs.append(bv)

    hip_arr = np.asarray(hips, dtype=np.uint32)
    bv_arr = np.asarray(bvs, dtype=np.float32)
    order = np.argsort(hip_arr)
    return hip_arr[order], bv_arr[order]


def _load() -> None:
    """Populate the module-level sorted lookup arrays (cached on disk)."""
    global _HIP_SORTED, _BV_SORTED
    if _HIP_SORTED is not None:
        return

    dat_path = _dat_path()
    cache_path = _cache_path()

    if (
        cache_path.exists()
        and dat_path.exists()
        and cache_path.stat().st_mtime >= dat_path.stat().st_mtime
    ):
        try:
            data = np.load(cache_path)
            _HIP_SORTED = data["hip"]
            _BV_SORTED = data["bv"]
            logger.info("Loaded B-V cache: %s (%d stars)", cache_path, len(_HIP_SORTED))
            return
        except Exception as e:
            logger.warning("B-V cache unreadable, reparsing %s: %s", dat_path, e)

    if not dat_path.exists():
        logger.warning(
            "hip_main.dat not found at %s; B-V correction disabled", dat_path
        )
        _HIP_SORTED = np.empty(0, dtype=np.uint32)
        _BV_SORTED = np.empty(0, dtype=np.float32)
        return

    logger.info("Parsing B-V from %s", dat_path)
    # Locals first: the module globals are Optional, so mypy cannot narrow
    # them across statements; the fresh arrays here never are.
    hip_sorted, bv_sorted = _parse_dat(dat_path)
    _HIP_SORTED, _BV_SORTED = hip_sorted, bv_sorted

    utils.create_path(cache_path.parent)
    try:
        np.savez(cache_path, hip=hip_sorted, bv=bv_sorted)
        logger.info("Wrote B-V cache: %s (%d stars)", cache_path, len(hip_sorted))
    except OSError as e:
        logger.warning("Failed to write B-V cache %s: %s", cache_path, e)


def get_bv(hip_ids) -> np.ndarray:
    """
    Look up B-V for an array of HIP numbers.

    Args:
        hip_ids: iterable of HIP catalog numbers (tetra3 ``matched_catID``).

    Returns:
        float array of B-V, ``nan`` where the star is missing or has no B-V.
    """
    _load()
    ids = np.asarray(list(hip_ids), dtype=np.int64)
    out = np.full(ids.shape, np.nan, dtype=np.float32)
    if _HIP_SORTED is None or _BV_SORTED is None or len(_HIP_SORTED) == 0:
        return out

    pos = np.searchsorted(_HIP_SORTED, ids)
    in_range = pos < len(_HIP_SORTED)
    pos_clamped = np.where(in_range, pos, 0)
    hit = in_range & (_HIP_SORTED[pos_clamped] == ids)
    out[hit] = _BV_SORTED[pos_clamped[hit]]
    return out


def reset_cache() -> None:
    """Drop the in-process cache (for tests)."""
    global _HIP_SORTED, _BV_SORTED
    _HIP_SORTED = None
    _BV_SORTED = None
