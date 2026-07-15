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
from typing import List, Optional, Sequence, Tuple

import numpy as np
from scipy import ndimage
from scipy.optimize import linear_sum_assignment


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
        peak: brightest detected-star peak (ADU), or None when nothing detected;
            retained for frame diagnostics.
        too_defocused: True when there is clear signal but every blob is larger
            than the size cap -- i.e. measurable stars exist but are too broad to
            quantify. Drives the "keep adjusting" hint.
        median_fwhm: Median area-equivalent FWHM estimate (px) over the same
            stars, for the statistics display. HFD remains the focus metric.
        blobs: Brightest detected blobs, including blobs too broad for an HFD
            measurement. The Focus screen uses their positions for raw star
            cutouts.
    """

    median_hfd: Optional[float]
    n_used: int
    background: float
    peak: Optional[float]
    too_defocused: bool
    median_fwhm: Optional[float] = None
    blobs: Tuple[Blob, ...] = ()


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
) -> Tuple[List[Blob], List[Blob], float, Optional[float]]:
    """Label connected regions above the detection threshold.

    Returns (usable_blobs, oversized_blobs, background, brightest_peak) where
    usable_blobs are blobs at least 2 px in size and no larger than the size cap,
    sorted brightest-first. ``oversized_blobs`` contains signal too defocused to
    measure but still useful for the visual focus tiles. ``brightest_peak`` is
    the peak of the brightest blob of any size, or None when nothing was detected.
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
        return [], [], background, None

    slices = ndimage.find_objects(labeled)

    usable: List[Blob] = []
    oversized: List[Blob] = []
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

        bbox_cy = (sl[0].start + sl[0].stop - 1) / 2.0
        bbox_cx = (sl[1].start + sl[1].stop - 1) / 2.0
        local_bg = _local_background(img, bbox_cy, bbox_cx, extent)

        # Center the display crop on the star's flux, not on the geometric
        # center of its thresholded bounding box. A one-pixel change at the
        # threshold boundary otherwise becomes a conspicuous jump after the
        # 10x focus enlargement.
        weights = np.clip(patch - local_bg, 0.0, None) * region_mask
        total_weight = float(weights.sum())
        if total_weight > 0.0:
            patch_y, patch_x = np.indices(patch.shape)
            cy = sl[0].start + float((patch_y * weights).sum() / total_weight)
            cx = sl[1].start + float((patch_x * weights).sum() / total_weight)
            local_bg = _local_background(img, cy, cx, extent)
        else:
            cy, cx = bbox_cy, bbox_cx
        blob = Blob(
            y=cy,
            x=cx,
            peak=peak,
            background=local_bg,
            extent=extent,
            size_px=size_px,
        )

        if extent > max_blob_px:
            oversized.append(blob)
        else:
            usable.append(blob)

    usable.sort(key=lambda b: b.peak, reverse=True)
    oversized.sort(key=lambda b: b.peak, reverse=True)
    return usable, oversized, background, brightest_peak


def track_blobs(
    previous: Sequence[Blob],
    candidates: Sequence[Blob],
    *,
    n: int = 4,
    max_relative_motion: float = 20.0,
    max_candidates: int = 12,
) -> Tuple[Blob, ...]:
    """Keep stars in stable slots while allowing the whole image to shift.

    Each previous/current star pair proposes a global translation. For every
    proposal, Hungarian assignment measures how well the remaining stars share
    that same motion. This uses the relative geometry of the 2--4 star pattern,
    so a bump while focusing can move the pattern by any distance without
    causing brightness-order swaps between quadrants. Small residual changes
    from wind, rotation, and focus breathing are accepted.

    When fewer than two stars can establish relative geometry, selection falls
    back to current brightness order. Missing slots are filled with the
    brightest unused candidates.
    """
    return tuple(
        blob
        for blob, _previous_index in track_blob_slots(
            previous,
            candidates,
            n=n,
            max_relative_motion=max_relative_motion,
            max_candidates=max_candidates,
        )
    )


def track_blob_slots(
    previous: Sequence[Blob],
    candidates: Sequence[Blob],
    *,
    n: int = 4,
    max_relative_motion: float = 20.0,
    max_candidates: int = 12,
) -> Tuple[Tuple[Blob, Optional[int]], ...]:
    """Track blobs and report which previous slot each result continues.

    The optional index is ``None`` for a newly selected replacement.  Keeping
    that distinction lets callers carry durable metadata such as a Hipparcos
    ID across geometrically tracked frames without accidentally giving a
    replacement star the departed star's identity.
    """
    current = tuple(candidates[:max_candidates])
    old = tuple(previous[:n])
    if len(old) < 2 or len(current) < 2:
        return tuple((blob, None) for blob in current[:n])

    old_xy = np.asarray([(blob.x, blob.y) for blob in old], dtype=np.float64)
    current_xy = np.asarray([(blob.x, blob.y) for blob in current], dtype=np.float64)
    best_score = None
    best_matches = None

    for old_anchor in old_xy:
        for current_anchor in current_xy:
            translation = current_anchor - old_anchor
            predicted = old_xy + translation
            distances = np.linalg.norm(
                predicted[:, np.newaxis, :] - current_xy[np.newaxis, :, :], axis=2
            )
            rows, columns = linear_sum_assignment(distances)
            valid = distances[rows, columns] <= max_relative_motion
            match_count = int(valid.sum())
            if match_count < 2:
                continue
            residual = float(distances[rows[valid], columns[valid]].mean())
            score = (match_count, -residual)
            if best_score is None or score > best_score:
                best_score = score
                best_matches = tuple(
                    (int(row), int(column))
                    for row, column, is_valid in zip(rows, columns, valid)
                    if is_valid
                )

    if best_matches is None:
        return tuple((blob, None) for blob in current[:n])

    slots: List[Optional[Tuple[Blob, Optional[int]]]] = [None] * min(len(old), n)
    used = set()
    for old_index, current_index in best_matches:
        slots[old_index] = (current[current_index], old_index)
        used.add(current_index)

    unused = (blob for index, blob in enumerate(current) if index not in used)
    for index, slot in enumerate(slots):
        if slot is None:
            replacement = next(unused, None)
            if replacement is not None:
                slots[index] = (replacement, None)
    while len(slots) < min(n, len(current)):
        replacement = next(unused, None)
        slots.append((replacement, None) if replacement is not None else None)

    return tuple(slot for slot in slots if slot is not None)


def match_catalog_ids(
    blobs: Sequence[Blob],
    matched_centroids: Sequence[Sequence[float]],
    matched_catalog_ids: Sequence[object],
    *,
    max_distance: float = 12.0,
) -> Tuple[Optional[object], ...]:
    """Associate solved catalogue IDs with focus blobs from the same frame.

    Tetra3 centroids and focus centroids are produced by different detectors,
    so they are close rather than necessarily pixel-identical.  A global
    one-to-one assignment prevents two focus blobs from claiming one HIP star;
    associations beyond ``max_distance`` are rejected.
    """
    identities: List[Optional[object]] = [None] * len(blobs)
    count = min(len(matched_centroids), len(matched_catalog_ids))
    if not blobs or count == 0:
        return tuple(identities)

    blob_xy = np.asarray([(blob.x, blob.y) for blob in blobs], dtype=np.float64)
    catalog_xy = np.asarray(
        [
            (matched_centroids[index][1], matched_centroids[index][0])
            for index in range(count)
        ],
        dtype=np.float64,
    )
    distances = np.linalg.norm(
        blob_xy[:, np.newaxis, :] - catalog_xy[np.newaxis, :, :], axis=2
    )
    rows, columns = linear_sum_assignment(distances)
    for row, column in zip(rows, columns):
        if distances[row, column] <= max_distance:
            identities[int(row)] = matched_catalog_ids[int(column)]
    return tuple(identities)


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


def full_width_half_maximum(np_image: np.ndarray, blob: Blob) -> float:
    """Area-equivalent FWHM diameter for one detected star, in raw pixels.

    Pixels above half the local peak-minus-background are counted inside a
    circular aperture around the blob. The diameter of a circle with that area
    equals the analytic FWHM for a circular Gaussian. This is a supplementary
    statistic; HFD remains preferable for saturated and defocused stars.
    """
    cy, cx = blob.y, blob.x
    height, width = np_image.shape
    aperture_radius = max(blob.extent, 4)
    y_min = max(0, int(cy) - aperture_radius)
    y_max = min(height, int(cy) + aperture_radius + 1)
    x_min = max(0, int(cx) - aperture_radius)
    x_max = min(width, int(cx) + aperture_radius + 1)

    patch = np.asarray(np_image[y_min:y_max, x_min:x_max], dtype=np.float32)
    y_grid, x_grid = np.ogrid[y_min:y_max, x_min:x_max]
    aperture = (x_grid - cx) ** 2 + (y_grid - cy) ** 2 <= aperture_radius**2
    half_max = blob.background + (blob.peak - blob.background) / 2.0
    area = int(np.count_nonzero((patch >= half_max) & aperture))
    if area == 0:
        return 0.0
    return 2.0 * float(np.sqrt(area / np.pi))


def focus_hfd(
    np_image: np.ndarray,
    *,
    n: int = 4,
    max_blob_px: int = 50,
    sigma_k: float = 5.0,
) -> FocusResult:
    """Measure focus on a single raw frame: detect -> measure -> median.

    Returns a :class:`FocusResult`. ``median_hfd`` is None when no usable star is
    found; ``too_defocused`` is True when signal is present but every blob is
    larger than ``max_blob_px``.
    """
    usable, oversized, background, brightest_peak = _find_blobs(
        np_image, max_blob_px=max_blob_px, sigma_k=sigma_k
    )
    display_blobs = tuple(
        sorted((*usable, *oversized), key=lambda blob: blob.peak, reverse=True)
    )

    if not usable:
        # No measurable star. If oversized blobs exist there is signal, but the
        # image is too defocused to quantify -> drive the "keep adjusting" hint.
        return FocusResult(
            median_hfd=None,
            n_used=0,
            background=background,
            peak=brightest_peak,
            too_defocused=bool(oversized),
            blobs=display_blobs,
        )

    img = np.asarray(np_image, dtype=np.float32)
    hfds = []
    fwhms = []
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
        fwhm = full_width_half_maximum(img, blob)
        if fwhm > 0.0:
            fwhms.append(fwhm)

    if not hfds:
        return FocusResult(
            median_hfd=None,
            n_used=0,
            background=background,
            peak=brightest_peak,
            too_defocused=bool(oversized),
            blobs=display_blobs,
        )

    return FocusResult(
        median_hfd=float(np.median(hfds)),
        n_used=len(hfds),
        background=background,
        peak=usable[0].peak,
        too_defocused=False,
        median_fwhm=float(np.median(fwhms)) if fwhms else None,
        blobs=display_blobs,
    )
