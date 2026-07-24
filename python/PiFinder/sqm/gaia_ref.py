"""
Gaia DR3 reference photometry for SQM zero points.

Bare (no IR-cut) sensors integrate roughly 400-1000 nm — almost exactly the
Gaia G passband — so referencing star fluxes against G with a small BP-RP
colour trim matches the sensor far better than Johnson V with a linear B-V
term (measured on the sweep archive: per-frame star scatter down 24-29% on
imx462/imx296, and the magnitude-dependent zero-point bias collapses).
IR-cut cameras (hq) remain on Hipparcos V, which *is* their native band.

Data: ``astro_data/hip_gaia_g.npz`` — HIP number -> (G, BP-RP) for every
Hipparcos star with a Gaia DR3 counterpart (built from
``gaiadr3.hipparcos2_best_neighbour`` x ``gaia_source``). Stars missing from
the table (a few percent, mostly the very brightest) fall back to the
Hipparcos V path in the caller.
"""

import logging
from pathlib import Path
from typing import Optional

import numpy as np

from PiFinder import utils

logger = logging.getLogger("SQM.GaiaRef")

_hip_index: Optional[dict] = None


def _dat_path() -> Path:
    return Path(utils.astro_data_dir, "hip_gaia_g.npz")


def _load() -> None:
    global _hip_index
    if _hip_index is not None:
        return
    try:
        z = np.load(_dat_path())
        _hip_index = {
            int(h): (float(g), float(c)) for h, g, c in zip(z["hip"], z["g"], z["bprp"])
        }
        logger.info("Loaded Gaia reference photometry for %d stars", len(_hip_index))
    except (FileNotFoundError, KeyError, ValueError) as e:
        logger.warning("Gaia reference table unavailable (%s); V-band fallback", e)
        _hip_index = {}


def get_g_bprp(hip_ids) -> np.ndarray:
    """(N, 2) array of (G, BP-RP) for HIP ids; NaN where unknown."""
    _load()
    assert _hip_index is not None
    out = np.full((len(hip_ids), 2), np.nan, dtype=np.float64)
    for i, hip in enumerate(hip_ids):
        try:
            row = _hip_index.get(int(hip))
        except (TypeError, ValueError):
            row = None
        if row is not None:
            out[i] = row
    return out


def reset_cache() -> None:
    global _hip_index
    _hip_index = None
