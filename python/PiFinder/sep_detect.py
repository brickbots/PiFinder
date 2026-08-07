#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
SEP (Source Extractor) star detection on the full-sensor RAW frame.

The production detector (cedar-detect) works on the processed 8-bit
512x512 solver frame, where the 12->8-bit stretch has already crushed
faint stars into a couple of levels under a bright (light-polluted)
sky background. This module detects in the 12-bit domain instead, on
the *uncropped* sensor frame:

1. 2x2 mean binning, for SNR (x2) and PSF energy concentration; on
   Bayer mosaics it also removes the RGGB modulation.
2. Estimate and subtract a mesh background (``sep.Background``) -- this
   removes light-pollution gradients and cloud glow, which is exactly
   the failure mode of a global threshold under a Seoul sky.
3. Extract sources against the local background RMS with a small
   matched filter, then rank by flux.

Returned centroids are in FULL-frame pixel coordinates (y, x), ready
for the solver-frame mapping in ``solver_frame_map``.

``sep`` is an optional dependency: importing this module never fails,
and ``detect_stars`` returns None when sep is unavailable.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger("Solver.SepDetect")

_sep = None
_sep_import_failed = False

# 3x3 gaussian-ish matched filter (SExtractor convention) -- correlates
# neighbouring pixels so PSF-shaped bumps beat single-pixel noise.
MATCHED_FILTER = np.array(
    [[1.0, 2.0, 1.0], [2.0, 4.0, 2.0], [1.0, 2.0, 1.0]], dtype=np.float32
)


def _sep_module():
    """Import sep lazily; remember a failure so we log it only once."""
    global _sep, _sep_import_failed
    if _sep is None and not _sep_import_failed:
        try:
            import sep

            _sep = sep
        except ImportError:
            _sep_import_failed = True
            logger.warning("sep not installed; SEP detection disabled")
    return _sep


@dataclass
class SepDetection:
    """Result of one SEP extraction, in full-frame pixel coordinates."""

    centroids: np.ndarray  # (N, 2) float (y, x), flux-descending
    fluxes: np.ndarray  # (N,) float, same order
    background_median: float  # binned-domain ADU
    background_rms: float  # binned-domain ADU
    elapsed_ms: float
    # Otherwise-keepable detections removed by the warm-pixel map. High
    # values on an empty sky are expected (the map is doing its job).
    masked_count: int = 0


def warm_pixel_excess(frame: np.ndarray) -> np.ndarray:
    """Per-pixel excess over the median of the 4 distance-2 neighbours
    (the same-Bayer-channel positions on a colour sensor; on a mono
    sensor simply a sparse neighbourhood -- valid either way).

    A warm/hot pixel is a single-pixel spike, so its excess is its full
    amplitude; extended structure (sky gradient, cloud, defocused
    star) raises the neighbours too and mostly cancels. A tightly focused
    star also shows excess -- which is why map *building* additionally
    requires recurrence at a fixed position across frames (stars move
    with the sky, warm pixels don't).
    """
    arr = np.asarray(frame, dtype=np.float32)
    h, w = arr.shape
    p = np.pad(arr, 2, mode="edge")
    neighbours = np.stack(
        [
            p[0:h, 2 : w + 2],  # same channel, y-2
            p[4 : h + 4, 2 : w + 2],  # y+2
            p[2 : h + 2, 0:w],  # x-2
            p[2 : h + 2, 4 : w + 4],  # x+2
        ]
    )
    return arr - np.median(neighbours, axis=0)


def build_warm_pixel_map(
    frames,
    min_excess_adu: float = 45.0,
    min_recurrence: float = 0.7,
) -> np.ndarray:
    """Warm-pixel positions recurring across frames, as (N, 2) int (y, x).

    Args:
        frames: Iterable of 2D raw arrays, all the same shape and in the
            same orientation the map will be applied in (solver_raw
            orientation: profile rot90 applied, no crop -- stage dumps are
            already in this orientation).
        min_excess_adu: Same-channel neighbour excess for a candidate.
        min_recurrence: Fraction of frames a position must be a candidate
            in. Static defects recur near 1.0; stars drift out within one
            frame interval, single-frame noise almost never repeats.
    """
    counts: Optional[np.ndarray] = None
    n_frames = 0
    for frame in frames:
        candidate = warm_pixel_excess(frame) > min_excess_adu
        if counts is None:
            counts = np.zeros(candidate.shape, dtype=np.uint16)
        counts += candidate
        n_frames += 1
    if counts is None or n_frames == 0:
        return np.empty((0, 2), dtype=np.int32)
    needed = max(1, int(np.ceil(min_recurrence * n_frames)))
    ys, xs = np.nonzero(counts >= needed)
    return np.column_stack((ys, xs)).astype(np.int32)


def bin2x2(frame: np.ndarray) -> np.ndarray:
    """Mean-bin each 2x2 block; trims odd edges."""
    arr = np.asarray(frame)
    h, w = arr.shape[0] // 2 * 2, arr.shape[1] // 2 * 2
    arr = arr[:h, :w].astype(np.float32)
    return (
        arr[0::2, 0::2] + arr[0::2, 1::2] + arr[1::2, 0::2] + arr[1::2, 1::2]
    ) * 0.25


def detect_stars(
    raw_frame: np.ndarray,
    sigma: float = 3.5,
    minarea: int = 3,
    max_stars: int = 48,
    edge_margin_px: int = 48,
    saturation_level: Optional[float] = None,
    warm_pixel_map: Optional[np.ndarray] = None,
    warm_pixel_radius_px: float = 4.0,
    max_semimajor_px: float = 2.0,
    max_npix: int = 40,
    cluster_radius_px: float = 50.0,
    cluster_max_neighbors: int = 1,
) -> Optional[SepDetection]:
    """
    Detect stars on a raw sensor frame (uint16 mosaic, any shape).

    Field lesson (Seoul, 2026-07-28 night): the uncropped frame's
    vignetted borders under cloud glow produce dozens of spurious
    extractions -- on a saturated-interior frame ALL "detections" sat at
    the frame edge with junk fluxes (huge blob, zeros, negatives). Hence
    the three quality filters here: an edge margin, a positive-flux
    requirement, and a saturation guard that reports an honest zero when
    the sky has burned the interior flat.

    Args:
        raw_frame: 2D raw sensor array (Bayer mosaic or mono).
        sigma: Extraction threshold in units of the local background RMS.
        minarea: Minimum connected pixels above threshold.
        max_stars: Keep at most this many, brightest (by flux) first.
        edge_margin_px: Drop detections within this many full-res pixels
            of the frame border (vignette / background-mesh edge zone).
        saturation_level: Sensor full scale (e.g. 4095 for 12-bit). When
            given and the binned interior median is at it, return zero
            detections instead of edge noise.
        warm_pixel_map: (N, 2) int (y, x) static-defect positions from
            ``build_warm_pixel_map``, same orientation as ``raw_frame``.
            Detections within ``warm_pixel_radius_px`` of a mapped position
            are dropped and counted in ``masked_count``.
        warm_pixel_radius_px: Match radius in full-res pixels (binning
            quantises centroids to a 2 px grid, so keep this >= 4).
        max_semimajor_px: Reject sources with a larger fitted semi-major
            axis (binned px). Cloud-edge texture is extended; real stars
            measured a <= 0.86 (p95), junk past 1.5 and NaN (degenerate
            fits, also rejected). Default 2.0 leaves defocus headroom.
            2026-07-28 night corpus.
        max_npix: Reject sources covering more binned pixels (stars p95
            10, cloud blobs to 188 -- same corpus; 40 = defocus headroom).
        cluster_radius_px / cluster_max_neighbors: Drop detections with
            more than ``cluster_max_neighbors`` others within the radius
            (full-res px). SEP deblends a bright cloud edge into tight
            clumps; measured real (tetra3-matched) stars had ZERO
            neighbours within 50 px in every case, junk up to 4.

    Returns:
        SepDetection with centroids in full-frame (y, x) pixels, or None
        if sep is unavailable or the frame is unusable.
    """
    sep = _sep_module()
    if sep is None:
        return None
    arr = np.asarray(raw_frame)
    if arr.ndim != 2 or arr.shape[0] < 8 or arr.shape[1] < 8:
        return None

    t0 = time.perf_counter()
    binned = bin2x2(arr)
    # sep requires C-contiguous native-endian float32
    data = np.ascontiguousarray(binned, dtype=np.float32)
    bkg = sep.Background(data, bw=32, bh=32)

    def _empty() -> SepDetection:
        return SepDetection(
            centroids=np.empty((0, 2)),
            fluxes=np.empty(0),
            background_median=float(bkg.globalback),
            background_rms=float(bkg.globalrms),
            elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        )

    if saturation_level is not None:
        h2, w2 = data.shape
        interior = data[h2 // 4 : -h2 // 4 or None, w2 // 4 : -w2 // 4 or None]
        if np.median(interior) >= 0.98 * saturation_level:
            return _empty()

    data_sub = data - bkg.back()
    objects = sep.extract(
        data_sub,
        thresh=sigma,
        err=bkg.rms(),
        filter_kernel=MATCHED_FILTER,
        minarea=minarea,
    )

    # A binned pixel (i, j) covers full-res pixels (2i, 2i+1) x (2j, 2j+1),
    # so its centre sits at 2*coord + 0.5 in full-frame coordinates.
    full_y = np.asarray(objects["y"]) * 2.0 + 0.5
    full_x = np.asarray(objects["x"]) * 2.0 + 0.5
    fluxes = np.asarray(objects["flux"], dtype=np.float64)
    semimajor = np.asarray(objects["a"], dtype=np.float64)
    npix = np.asarray(objects["npix"], dtype=np.int64)

    h, w = arr.shape
    keep = (
        (fluxes > 0)
        & (full_y >= edge_margin_px)
        & (full_y < h - edge_margin_px)
        & (full_x >= edge_margin_px)
        & (full_x < w - edge_margin_px)
        # Point-source shape gate: extended or degenerate (NaN) fits are
        # cloud texture, not stars (thresholds measured -- see docstring).
        & np.isfinite(semimajor)
        & (semimajor <= max_semimajor_px)
        & (npix <= max_npix)
    )

    # Warm-pixel map: drop otherwise-keepable detections sitting on a known
    # static defect (before the top-N cap, so defects can't crowd out stars).
    masked_count = 0
    if warm_pixel_map is not None and len(warm_pixel_map) and keep.any():
        wp = np.asarray(warm_pixel_map, dtype=np.float64)
        d2 = (
            (full_y[:, None] - wp[None, :, 0]) ** 2
            + (full_x[:, None] - wp[None, :, 1]) ** 2
        ).min(axis=1)
        warm = d2 <= warm_pixel_radius_px**2
        masked_count = int((keep & warm).sum())
        keep &= ~warm

    full_y, full_x, fluxes = full_y[keep], full_x[keep], fluxes[keep]

    # Cluster gate: SEP deblends bright cloud edges into tight clumps of
    # "sources"; real stars at this plate scale are isolated (measured 0
    # neighbours within 50 px on every tetra3-matched star).
    if len(full_y) > 1:
        d2 = (full_y[:, None] - full_y[None, :]) ** 2 + (
            full_x[:, None] - full_x[None, :]
        ) ** 2
        neighbours = (d2 <= cluster_radius_px**2).sum(axis=1) - 1
        isolated = neighbours <= cluster_max_neighbors
        full_y, full_x, fluxes = full_y[isolated], full_x[isolated], fluxes[isolated]

    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    order = np.argsort(fluxes)[::-1][:max_stars]
    return SepDetection(
        centroids=np.column_stack((full_y[order], full_x[order])),
        fluxes=fluxes[order],
        background_median=float(bkg.globalback),
        background_rms=float(bkg.globalrms),
        elapsed_ms=elapsed_ms,
        masked_count=masked_count,
    )
