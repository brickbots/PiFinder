#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
End-to-end equivalence of the SEP full-frame solve path.

Projects real catalog stars (tetra3's own star table) onto a synthetic
full-sensor frame, then solves the same sky twice:

* production path: centred crop -> 512 resize -> stage-5 rotation
* SEP path: full-frame centroids -> rotate_centroids ->
  map_target_pixel_to_frame -> fov_estimate_deg

and asserts both return the same Roll and the same aligned pointing at
the (off-centre) target pixel. This is the proof that swapping the
detection frame cannot disturb tracking, alignment, or push-to.
"""

import numpy as np
import pytest

from PiFinder import solver_frame_map as sfm
from PiFinder import utils

tetra3 = pytest.importorskip("tetra3")

# imx462 geometry (the fielded camera)
FULL_H, FULL_W = 1080, 1920
CROP_Y0, CROP_X0 = 50, 470
CROP_W = 980
PLATE_SCALE = sfm.SOLVER_FOV_DEG / CROP_W  # deg per full-res px
TARGET_512 = (300.0, 340.0)  # off-centre alignment point, rotated-512 space


def _project_stars(t3, ra0_deg, dec0_deg, max_stars=80):
    """Gnomonic projection of catalog stars onto the full frame (y, x)."""
    st = t3.star_table  # columns: ra, dec (rad), x, y, z, mag
    ra0, dec0 = np.deg2rad(ra0_deg), np.deg2rad(dec0_deg)
    cosd = np.sin(dec0) * np.sin(st[:, 1]) + np.cos(dec0) * np.cos(st[:, 1]) * np.cos(
        st[:, 0] - ra0
    )
    sel = np.where(cosd > np.cos(np.deg2rad(13)))[0]
    sel = sel[np.argsort(st[sel, -1])][:max_stars]
    ra, dec = st[sel, 0], st[sel, 1]
    cosc = np.sin(dec0) * np.sin(dec) + np.cos(dec0) * np.cos(dec) * np.cos(ra - ra0)
    x_ang = np.rad2deg(np.cos(dec) * np.sin(ra - ra0) / cosc)
    y_ang = np.rad2deg(
        (np.cos(dec0) * np.sin(dec) - np.sin(dec0) * np.cos(dec) * np.cos(ra - ra0))
        / cosc
    )
    cy, cx = (FULL_H - 1) / 2, (FULL_W - 1) / 2
    x_px = cx - x_ang / PLATE_SCALE
    y_px = cy - y_ang / PLATE_SCALE
    inside = (x_px >= 0) & (x_px < FULL_W) & (y_px >= 0) & (y_px < FULL_H)
    return np.column_stack((y_px[inside], x_px[inside]))


@pytest.mark.unit
def test_sep_fullframe_solve_matches_production_pointing():
    db_path = utils.tetra3_dir / "data" / "default_database.npz"
    if not db_path.exists():
        pytest.skip("tetra3 default database not present (submodule not populated)")
    t3 = tetra3.Tetra3(str(db_path))
    cents_full = _project_stars(t3, ra0_deg=84.0, dec0_deg=0.0)
    assert len(cents_full) > 30

    # target_pixel as persisted: rotated-512 space (stage-5 rotation 90)
    tp512r, _ = sfm.rotate_centroids(np.array([TARGET_512]), (512, 512), 90)
    tp512r = tuple(tp512r[0])

    # --- production path
    yc = cents_full[:, 0] - CROP_Y0
    xc = cents_full[:, 1] - CROP_X0
    ok = (yc >= 0) & (yc < CROP_W) & (xc >= 0) & (xc < CROP_W)
    c512 = np.column_stack((yc[ok], xc[ok])) * (sfm.SOLVER_FRAME_PX / CROP_W)
    c512r, canvas512 = sfm.rotate_centroids(c512, (512, 512), 90)
    sol_prod = t3.solve_from_centroids(
        c512r,
        canvas512,
        fov_estimate=12.0,
        fov_max_error=4.0,
        match_max_error=0.005,
        target_pixel=tp512r,
        solve_timeout=1000,
    )
    assert sol_prod.get("RA") is not None

    # --- SEP full-frame path (exactly what sep_shadow.solve does)
    cfull_r, canvas_full = sfm.rotate_centroids(cents_full, (FULL_H, FULL_W), 90)
    tp_full = sfm.map_target_pixel_to_frame(tp512r, canvas_full, CROP_W)
    fov = sfm.fov_estimate_deg(canvas_full[1], CROP_W)
    sol_sep = t3.solve_from_centroids(
        cfull_r,
        canvas_full,
        fov_estimate=fov,
        fov_max_error=fov / 3,
        match_max_error=0.005,
        target_pixel=tp_full,
        solve_timeout=1000,
    )
    assert sol_sep.get("RA") is not None

    # The wider frame must see MORE of the sky's stars
    assert sol_sep["Matches"] > sol_prod["Matches"]

    # Same camera pointing and identical Roll convention
    assert abs(sol_prod["RA"] - sol_sep["RA"]) * 3600 < 120
    assert abs(sol_prod["Dec"] - sol_sep["Dec"]) * 3600 < 120
    droll = abs((sol_prod["Roll"] - sol_sep["Roll"] + 180) % 360 - 180)
    assert droll < 0.05

    # Aligned pointing at the target pixel agrees to within a fit residual
    assert abs(sol_prod["RA_target"] - sol_sep["RA_target"]) * 3600 < 60
    assert abs(sol_prod["Dec_target"] - sol_sep["Dec_target"]) * 3600 < 60

    # --- hybrid alignment: solving the ALIGNMENT DIRECTION through both
    # paths must land on the same 512-space target pixel. Ask each solve
    # where a fixed sky coordinate falls, and map the SEP answer back with
    # map_frame_pixel_to_target (what sep_shadow.solve does during align).
    sky = [[sol_prod["RA_target"], sol_prod["Dec_target"]]]
    sol_prod_a = t3.solve_from_centroids(
        c512r,
        canvas512,
        fov_estimate=12.0,
        fov_max_error=4.0,
        match_max_error=0.005,
        target_sky_coord=sky,
        solve_timeout=1000,
    )
    sol_sep_a = t3.solve_from_centroids(
        cfull_r,
        canvas_full,
        fov_estimate=fov,
        fov_max_error=fov / 3,
        match_max_error=0.005,
        target_sky_coord=sky,
        solve_timeout=1000,
    )
    assert sol_prod_a.get("y_target") is not None
    assert sol_sep_a.get("y_target") is not None
    sep_tp512 = sfm.map_frame_pixel_to_target(
        (sol_sep_a["y_target"], sol_sep_a["x_target"]), canvas_full, CROP_W
    )
    dy = abs(sep_tp512[0] - sol_prod_a["y_target"])
    dx = abs(sep_tp512[1] - sol_prod_a["x_target"])
    # within one 512-space pixel (~84 arcsec of plate scale)
    assert dy < 1.0 and dx < 1.0


@pytest.mark.unit
def test_target_pixel_mapping_round_trip():
    """map_frame_pixel_to_target inverts map_target_pixel_to_frame exactly."""
    canvas = (1920, 1080)  # rotated full frame (imx462, 90 deg)
    for tp in [(256.0, 256.0), (100.5, 400.25), (0.0, 511.0)]:
        full = sfm.map_target_pixel_to_frame(tp, canvas, 980)
        back = sfm.map_frame_pixel_to_target(full, canvas, 980)
        assert abs(back[0] - tp[0]) < 1e-9
        assert abs(back[1] - tp[1]) < 1e-9
