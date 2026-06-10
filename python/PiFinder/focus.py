#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Self-contained focus-quality measurement for the Focus screen.

This module implements a lightweight star detector and Half-Flux Diameter (HFD)
measurement that run in the main (UI) process on the raw 512x512 camera frame.
It is **deliberately independent** of the solver's tetra3/Cedar centroids and of
SQM photometry: a badly defocused frame does not plate-solve, so solver-derived
stars vanish at exactly the moment focus help is needed most. See
``docs/adr/0005-focus-hfd-self-contained-in-ui.md`` and the "Focus indicator"
section of ``docs/ax/ui/CONTEXT.md`` for the design rationale and vocabulary.

The detector is tuned to *accept* broad/defocused blobs (the opposite of Cedar's
tight-star tuning), rejecting only single-pixel hot pixels and blobs too large to
measure usefully. All measurement is performed on the raw frame, never on the
display-stretched copy, so the reported HFD never depends on how the image looks.

Pure numpy/scipy only -- no PIL/display or UIModule dependencies -- so it is
unit-testable against synthetic blobs of known width.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from scipy import ndimage


@dataclass
class Blob:
    """A detected star (broad or tight) in the raw frame.

    Attributes:
        y, x: blob center in raw-frame pixel coordinates (numpy row, col).
        peak: peak pixel value (ADU) inside the blob.
        background: local background level (ADU/pixel) around the blob.
        extent: largest bounding-box dimension in pixels (~ the blob diameter).
        size_px: number of connected pixels above the detection threshold.
    """

    y: float
    x: float
    peak: float
    background: float
    extent: int
    size_px: int


@dataclass
class FocusResult:
    """Outcome of measuring focus on a single frame.

    Attributes:
        median_hfd: median HFD (px) over the brightest detected stars, or None
            when there is no usable star to measure.
        n_used: number of detected stars HFD was measured on.
        background: global background level (ADU) of the frame.
        peak: brightest detected-star peak (ADU), or None when nothing detected.
            Used as the white point for the display stretch.
        too_defocused: True when there is clear signal but every blob is larger
            than the size cap -- i.e. measurable stars exist but are too broad to
            quantify. Drives the "keep adjusting" hint.
    """

    median_hfd: Optional[float]
    n_used: int
    background: float
    peak: Optional[float]
    too_defocused: bool


def _estimate_background_noise(np_image: np.ndarray) -> Tuple[float, float]:
    """Return (background, noise_sigma) using robust median / MAD statistics.

    MAD (median absolute deviation) is insensitive to the bright star pixels and
    to hot pixels, so the threshold tracks the sky floor rather than the signal.
    A small floor on sigma avoids a zero threshold on a perfectly flat frame.
    """
    background = float(np.median(np_image))
    mad = float(np.median(np.abs(np_image - background)))
    sigma = 1.4826 * mad
    return background, max(sigma, 1.0)


def _local_background(np_image: np.ndarray, cy: float, cx: float, extent: int) -> float:
    """Median of an annulus around (cy, cx), sized from the blob extent.

    Independent re-implementation of the bbox + radial-distance patch geometry
    also used by SQM (no shared code -- see ADR 0005). Falls back to the global
    median if the annulus lands off-frame.
    """
    height, width = np_image.shape
    radius = max(extent, 4)
    inner = radius + 2
    outer = radius + 8

    y_min = max(0, int(cy) - outer)
    y_max = min(height, int(cy) + outer + 1)
    x_min = max(0, int(cx) - outer)
    x_max = min(width, int(cx) + outer + 1)

    patch = np_image[y_min:y_max, x_min:x_max]
    y_grid, x_grid = np.ogrid[y_min:y_max, x_min:x_max]
    dist_sq = (x_grid - cx) ** 2 + (y_grid - cy) ** 2
    annulus = (dist_sq > inner**2) & (dist_sq <= outer**2)

    annulus_pixels = patch[annulus]
    if annulus_pixels.size > 0:
        return float(np.median(annulus_pixels))
    return float(np.median(np_image))


def _find_blobs(
    np_image: np.ndarray,
    *,
    max_blob_px: int,
    sigma_k: float,
) -> Tuple[List[Blob], int, float, Optional[float]]:
    """Label connected regions above the detection threshold.

    Returns (usable_blobs, n_oversized, background, brightest_peak) where
    usable_blobs are blobs at least 2 px in size and no larger than the size cap,
    sorted brightest-first. ``n_oversized`` counts blobs that exceed the size cap
    (signal present but too defocused to measure). ``brightest_peak`` is the peak
    of the brightest blob of any size, or None when nothing was detected.
    """
    img = np.asarray(np_image, dtype=np.float32)
    background, sigma = _estimate_background_noise(img)
    threshold = background + sigma_k * sigma

    # Detect on a lightly smoothed copy so per-pixel noise does not fragment a
    # broad defocused blob into many spurious tiny "stars" at its threshold ring
    # (which would hide the too-defocused state). Measurement below still uses
    # the raw frame -- see ADR 0005.
    smoothed = ndimage.gaussian_filter(img, sigma=1.0)
    mask = smoothed > threshold
    labeled, n_labels = ndimage.label(mask)
    if n_labels == 0:
        return [], 0, background, None

    slices = ndimage.find_objects(labeled)

    usable: List[Blob] = []
    n_oversized = 0
    brightest_peak: Optional[float] = None

    for label_idx, sl in enumerate(slices, start=1):
        if sl is None:
            continue
        region_mask = labeled[sl] == label_idx

        patch = img[sl]
        peak = float(patch[region_mask].max())
        if brightest_peak is None or peak > brightest_peak:
            brightest_peak = peak

        # Count pixels above threshold in the RAW frame (not the smoothed copy)
        # so a single-pixel hot pixel -- which smoothing spreads into a small
        # blob -- is still rejected as a one-pixel spike.
        size_px = int(((patch > threshold) & region_mask).sum())
        if size_px < 2:
            continue

        height = sl[0].stop - sl[0].start
        width = sl[1].stop - sl[1].start
        extent = int(max(height, width))

        # Too broad to measure usefully -- treat as "too defocused".
        if extent > max_blob_px:
            n_oversized += 1
            continue

        cy = (sl[0].start + sl[0].stop - 1) / 2.0
        cx = (sl[1].start + sl[1].stop - 1) / 2.0
        local_bg = _local_background(img, cy, cx, extent)

        usable.append(
            Blob(
                y=cy,
                x=cx,
                peak=peak,
                background=local_bg,
                extent=extent,
                size_px=size_px,
            )
        )

    usable.sort(key=lambda b: b.peak, reverse=True)
    return usable, n_oversized, background, brightest_peak


def detect_stars(
    np_image: np.ndarray,
    *,
    max_blob_px: int = 50,
    sigma_k: float = 5.0,
    n: int = 5,
) -> List[Blob]:
    """Find up to ``n`` of the brightest usable blobs in the raw frame.

    Tuned to accept broad/defocused blobs but reject blobs larger than
    ``max_blob_px`` (too defocused to measure) and single-pixel hot pixels.
    Returned blobs are sorted brightest-first.
    """
    usable, _, _, _ = _find_blobs(np_image, max_blob_px=max_blob_px, sigma_k=sigma_k)
    return usable[:n]


def half_flux_diameter(
    np_image: np.ndarray,
    center: Tuple[float, float],
    background: float,
    *,
    aperture_radius: int = 25,
) -> float:
    """Half-Flux Diameter (px) for a single star centered at ``center`` (y, x).

    HFD = 2 * sum(flux_i * r_i) / sum(flux_i) over aperture pixels, where
    flux_i = pixel_i - background clamped to >= 0. Stable on saturated cores and
    broad defocused blobs, where a Gaussian (FWHM) fit fails.
    """
    cy, cx = center
    height, width = np_image.shape

    y_min = max(0, int(cy) - aperture_radius)
    y_max = min(height, int(cy) + aperture_radius + 1)
    x_min = max(0, int(cx) - aperture_radius)
    x_max = min(width, int(cx) + aperture_radius + 1)

    patch = np.asarray(np_image[y_min:y_max, x_min:x_max], dtype=np.float32)
    y_grid, x_grid = np.ogrid[y_min:y_max, x_min:x_max]
    dist = np.sqrt((x_grid - cx) ** 2 + (y_grid - cy) ** 2)
    aperture = dist <= aperture_radius

    flux = np.clip(patch - background, 0.0, None)
    flux = np.where(aperture, flux, 0.0)

    total_flux = float(flux.sum())
    if total_flux <= 0.0:
        return 0.0

    weighted_r = float((flux * dist).sum())
    return 2.0 * weighted_r / total_flux


def focus_hfd(
    np_image: np.ndarray,
    *,
    n: int = 5,
    max_blob_px: int = 50,
    sigma_k: float = 5.0,
) -> FocusResult:
    """Measure focus on a single raw frame: detect -> measure -> median.

    Returns a :class:`FocusResult`. ``median_hfd`` is None when no usable star is
    found; ``too_defocused`` is True when signal is present but every blob is
    larger than ``max_blob_px``.
    """
    usable, n_oversized, background, brightest_peak = _find_blobs(
        np_image, max_blob_px=max_blob_px, sigma_k=sigma_k
    )

    if not usable:
        # No measurable star. If oversized blobs exist there is signal, but the
        # image is too defocused to quantify -> drive the "keep adjusting" hint.
        return FocusResult(
            median_hfd=None,
            n_used=0,
            background=background,
            peak=brightest_peak,
            too_defocused=n_oversized > 0,
        )

    img = np.asarray(np_image, dtype=np.float32)
    hfds = []
    for blob in usable[:n]:
        aperture_radius = int(np.clip(blob.extent, 10, max_blob_px))
        hfd = half_flux_diameter(
            img,
            (blob.y, blob.x),
            blob.background,
            aperture_radius=aperture_radius,
        )
        if hfd > 0.0:
            hfds.append(hfd)

    if not hfds:
        return FocusResult(
            median_hfd=None,
            n_used=0,
            background=background,
            peak=brightest_peak,
            too_defocused=n_oversized > 0,
        )

    return FocusResult(
        median_hfd=float(np.median(hfds)),
        n_used=len(hfds),
        background=background,
        peak=usable[0].peak,
        too_defocused=False,
    )
