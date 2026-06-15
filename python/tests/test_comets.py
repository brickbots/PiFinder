"""Unit tests for the vectorized comet propagation in PiFinder.comets.

The vectorized path (``_calc_comets_vectorized``) replaced a per-comet
skyfield loop that pegged a CPU core continuously while locked on a target
(see comets.py for the full root-cause note).  These tests pin the fast path
to the slow per-comet path (``_calc_comets_per_comet``, kept as the reference
oracle / fallback) so a future skyfield release or MPC-format change that
breaks the batched call is caught in CI rather than in the field.
"""

import math
from datetime import datetime, timezone

import numpy as np
import pytest

from PiFinder.calc_utils import sf_utils
import PiFinder.comets as comets

# Fixed observer + time so both code paths see identical inputs.
_LAT, _LON, _ALT = 37.5, -122.3, 100.0
_DT = datetime(2026, 6, 14, 6, 0, 0, tzinfo=timezone.utc)


def _angsep_arcsec(ra1, dec1, ra2, dec2):
    """Great-circle separation in arcseconds (robust to the 0/360 RA seam)."""
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    sd = math.sin((d2 - d1) / 2) ** 2
    sr = math.sin((r2 - r1) / 2) ** 2
    a = sd + math.cos(d1) * math.cos(d2) * sr
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(a)))) * 3600.0


def _spread_sample(df, n):
    """Pick ~n rows spread across the file (diverse orbital elements)."""
    step = max(1, len(df) // n)
    return df.iloc[::step]


@pytest.mark.unit
def test_vectorized_matches_per_comet_positions():
    """Vectorized RA/Dec/mag/distance must equal the per-comet oracle.

    Magnitudes are forced bright so every sampled comet survives the mag
    cut and gets compared (the comparison is of the propagation, not the
    filter).  A diverse spread of eccentricities exercises the
    elliptic/parabolic/hyperbolic conic branches, and the tight RA/Dec
    tolerance also guards the J2000 framing rotation (a missing/wrong epoch
    matrix showed up as a ~15" systematic shift during development).
    """
    sf_utils.set_location(_LAT, _LON, _ALT)
    df = comets._load_comets_dataframe()
    sample = _spread_sample(df, 40).copy()
    # Force every comet through the mag<=15 gate regardless of distance.
    sample["magnitude_g"] = -50.0
    sample["magnitude_k"] = 0.0

    vec = comets._calc_comets_vectorized(sample, _DT)
    oracle = comets._calc_comets_per_comet(sample, _DT)

    assert set(vec) == set(oracle)
    assert len(vec) >= 20  # sanity: the sample really did flow through

    for name in oracle:
        o, v = oracle[name], vec[name]
        sep = _angsep_arcsec(o["radec"][0], o["radec"][1], v["radec"][0], v["radec"][1])
        assert sep < 0.05, f'{name}: RA/Dec off by {sep:.4f}"'
        assert v["mag"] == pytest.approx(o["mag"], abs=1e-6, nan_ok=True)
        assert v["earth_distance"] == pytest.approx(o["earth_distance"], rel=1e-9)
        assert v["sun_distance"] == pytest.approx(o["sun_distance"], rel=1e-9)


@pytest.mark.unit
def test_vectorized_matches_per_comet_on_real_filter():
    """With real magnitudes, both paths must keep exactly the same comets."""
    sf_utils.set_location(_LAT, _LON, _ALT)
    df = comets._load_comets_dataframe()

    vec = comets._calc_comets_vectorized(df, _DT)
    # Run the (slow) oracle only over the comets the fast path kept, then
    # confirm none of those would actually have been dropped by the oracle.
    oracle = comets._calc_comets_per_comet(df[df["designation"].isin(vec)], _DT)
    assert set(vec) == set(oracle)


@pytest.mark.unit
def test_mag_filter_keeps_nan_and_drops_dim():
    """Filter parity, including the quirk that NaN-mag comets are kept.

    The old per-comet code filtered with ``if mag > 15``; ``nan > 15`` is
    False, so unknown-magnitude comets were *included*.  The vectorized cut
    is phrased as ``~(mag > 15)`` to preserve that, and both paths must agree.
    """
    sf_utils.set_location(_LAT, _LON, _ALT)
    df = comets._load_comets_dataframe()
    three = df.iloc[:3].copy()
    names = list(three["designation"])

    # bright -> kept, dim -> dropped, NaN -> kept (the quirk)
    three["magnitude_g"] = [-50.0, 99.0, np.nan]
    three["magnitude_k"] = [0.0, 0.0, 0.0]

    vec = comets._calc_comets_vectorized(three, _DT)
    oracle = comets._calc_comets_per_comet(three, _DT)

    assert set(vec) == set(oracle)
    assert names[0] in vec  # bright kept
    assert names[1] not in vec  # dim dropped
    assert names[2] in vec  # NaN kept
    assert math.isnan(vec[names[2]]["mag"])


@pytest.mark.unit
def test_calc_comets_empty_without_location():
    """No observer location -> empty result (no crash)."""
    # Save/restore: set_location() short-circuits when _last_location is
    # unchanged, so leaving these nulled would break later tests that reuse
    # the same coordinates.
    saved_loc = sf_utils.observer_loc
    saved_last = sf_utils._last_location
    try:
        sf_utils.observer_loc = None
        sf_utils._last_location = None
        assert comets.calc_comets(_DT) == {}
    finally:
        sf_utils.observer_loc = saved_loc
        sf_utils._last_location = saved_last


@pytest.mark.unit
def test_vectorized_single_comet_matches_oracle():
    """N==1: skyfield's propagate() squeezes one comet to shape (3,); the
    ndim==1 reshape in the vectorized path must restore (3, 1).  Not hit by
    the multi-comet tests, so cover it explicitly."""
    sf_utils.set_location(_LAT, _LON, _ALT)
    df = comets._load_comets_dataframe()
    one = df.iloc[[0]].copy()
    one["magnitude_g"] = -50.0  # force visible
    one["magnitude_k"] = 0.0

    vec = comets._calc_comets_vectorized(one, _DT)
    oracle = comets._calc_comets_per_comet(one, _DT)

    assert set(vec) == set(oracle)
    assert len(vec) == 1
    name = next(iter(vec))
    o, v = oracle[name], vec[name]
    sep = _angsep_arcsec(o["radec"][0], o["radec"][1], v["radec"][0], v["radec"][1])
    assert sep < 0.05
    assert v["mag"] == pytest.approx(o["mag"], abs=1e-6)
    assert v["earth_distance"] == pytest.approx(o["earth_distance"], rel=1e-9)
    assert v["sun_distance"] == pytest.approx(o["sun_distance"], rel=1e-9)


@pytest.mark.unit
def test_calc_comets_falls_back_on_vectorized_error(monkeypatch):
    """If the batched path raises, calc_comets must fall back to the per-comet
    path and still return the same comets (not silently drop them)."""
    sf_utils.set_location(_LAT, _LON, _ALT)
    df = comets._load_comets_dataframe()
    visible = list(comets._calc_comets_vectorized(df, _DT))
    assert visible, "expected at least one visible comet on the fixed date"

    def boom(*args, **kwargs):
        raise RuntimeError("simulated skyfield breakage")

    monkeypatch.setattr(comets, "_calc_comets_vectorized", boom)
    # comet_names keeps the (slow) per-comet fallback bounded to the few
    # already-known-visible comets so the test stays fast.
    result = comets.calc_comets(_DT, comet_names=visible)
    assert set(result) == set(visible)


@pytest.mark.unit
def test_calc_comets_respects_comet_names_filter():
    """comet_names restricts the result to the requested designations."""
    sf_utils.set_location(_LAT, _LON, _ALT)
    df = comets._load_comets_dataframe()
    visible = list(comets._calc_comets_vectorized(df, _DT))
    assert len(visible) >= 2
    subset = visible[:1]
    result = comets.calc_comets(_DT, comet_names=subset)
    assert set(result) == set(subset)
