"""
Rolling aperture (wing-loss) correction for SQM photometry.

The lens PSF has heavy wings: a substantial fraction of each star's flux falls
outside the small photometry aperture, so the fitted photometric zero point
(``mzero``) comes out too low and SQM reads too bright. The wing fraction is a
property of the optics (focus, lens halo) and drifts slowly -- it is NOT a
per-frame quantity. Measuring it per frame injects noise and, worse, an
exposure dependence (wings sink below the noise on short exposures).

So this estimator splits measure from apply, like ``PedestalEstimator``:

- **Measure** only on frames that can support it: bright, unsaturated,
  uncrowded matched stars whose radial profile flattens within the search
  range. Growing rings around each star, the ring level keeps declining while
  inside the star's wings; the first radius where the decline stops is the
  wing boundary. Sky comes from beyond it, total flux from inside it, and the
  enclosed fraction is ``f = flux(aperture) / flux(total)``.
- **Smooth** the per-frame samples in a rolling window (median).
- **Apply** the smoothed ``-2.5*log10(f)`` to ``mzero`` on every frame.
"""

import logging
from collections import deque
from typing import Optional

import numpy as np

logger = logging.getLogger("SQM.Wings")


class WingEstimator:
    """Rolling estimate of the aperture enclosed-flux fraction ``f``."""

    def __init__(
        self,
        aperture_radius: int = 5,
        max_radius: int = 29,
        ring_step: int = 2,
        max_samples: int = 20,
        min_samples: int = 3,
        min_stars: int = 3,
        min_core_snr: float = 50.0,
    ):
        """
        Args:
            aperture_radius: production photometry aperture the correction is for.
            max_radius: outermost search radius for the wing boundary.
            ring_step: radial width of each profile ring.
            max_samples: rolling window of per-frame ``f`` samples.
            min_samples: samples needed before the correction is applied.
            min_stars: per-frame minimum of usable stars for one ``f`` sample.
            min_core_snr: core flux must exceed this multiple of the per-pixel
                sky noise for a star's wings to be measurable.
        """
        self.aperture_radius = aperture_radius
        self.max_radius = max_radius
        self.ring_edges = list(range(aperture_radius, max_radius + 1, ring_step))
        self.max_samples = max_samples
        self.min_samples = min_samples
        self.min_stars = min_stars
        self.min_core_snr = min_core_snr
        self._samples: deque = deque(maxlen=max_samples)

    def _measure_star(self, patch: np.ndarray, r: np.ndarray) -> Optional[float]:
        """Enclosed fraction for one star patch, or None if unmeasurable."""
        levels = []
        for r0, r1 in zip(self.ring_edges[:-1], self.ring_edges[1:]):
            ring = patch[(r > r0) & (r <= r1)]
            if len(ring) == 0:
                return None
            levels.append(float(np.median(ring)))
        levels_arr = np.asarray(levels)

        # Ring-level noise scale from the outermost rings (assumed sky).
        noise = max(float(np.std(levels_arr[-4:])), 1e-3)

        # Wing boundary: first ring from which no significant decline remains.
        cut_idx = len(levels_arr) - 1
        for i in range(len(levels_arr)):
            if levels_arr[i] - levels_arr[i:].min() <= noise:
                cut_idx = i
                break

        # Crowding guard: a profile rising again beyond the boundary means a
        # neighbouring star sits inside the search range.
        if np.any(levels_arr[cut_idx:] > levels_arr[cut_idx] + 4 * noise):
            return None

        wing_radius = self.ring_edges[cut_idx]
        sky_pixels = patch[(r > wing_radius) & (r <= self.max_radius)]
        if len(sky_pixels) == 0:
            return None
        sky = float(np.median(sky_pixels))

        signal = patch - sky
        core_flux = float(signal[r <= self.aperture_radius].sum())
        total_flux = float(signal[r <= wing_radius].sum())

        # SNR gate: wings must stand above the sky noise to be measurable.
        pixel_noise = float(np.std(sky_pixels))
        if core_flux < self.min_core_snr * pixel_noise:
            return None
        if total_flux <= 0 or core_flux <= 0:
            return None

        f = core_flux / total_flux
        if not (0.2 < f <= 1.0):
            return None  # unphysical; likely crowding or a bad profile
        return f

    def add_frame(
        self,
        image: np.ndarray,
        centroids,
        saturation_threshold: float,
    ) -> Optional[float]:
        """
        Measure one frame's enclosed fraction from its matched star centroids.

        Args:
            image: linear photometry image (raw green channel).
            centroids: matched star centroids, (y, x) rows, in `image` pixels.
            saturation_threshold: pixel level above which a star core is skipped.

        Returns:
            The frame's median enclosed fraction if measurable, else None.
        """
        if image is None or centroids is None or len(centroids) == 0:
            return None
        height, width = image.shape
        box = self.max_radius + 1
        fractions = []
        for cy, cx in centroids:
            iy, ix = int(round(cy)), int(round(cx))
            if iy - box < 0 or ix - box < 0 or iy + box >= height or ix + box >= width:
                continue
            patch = image[iy - box : iy + box + 1, ix - box : ix + box + 1].astype(
                np.float64
            )
            yy, xx = np.mgrid[-box : box + 1, -box : box + 1]
            r = np.sqrt((yy + (cy - iy)) ** 2 + (xx + (cx - ix)) ** 2)
            if patch[r <= self.aperture_radius].max() >= saturation_threshold:
                continue
            f = self._measure_star(patch, r)
            if f is not None:
                fractions.append(f)

        if len(fractions) < self.min_stars:
            return None
        sample = float(np.median(fractions))
        self._samples.append(sample)
        logger.debug(
            "Wing sample f=%.3f from %d stars (window %d)",
            sample,
            len(fractions),
            len(self._samples),
        )
        return sample

    def enclosed_fraction(self) -> Optional[float]:
        """Smoothed enclosed fraction, or None until conditioned."""
        if len(self._samples) < self.min_samples:
            return None
        return float(np.median(self._samples))

    def correction(self) -> float:
        """Additive mzero correction ``-2.5*log10(f)``; 0.0 until conditioned."""
        f = self.enclosed_fraction()
        if f is None:
            return 0.0
        return float(-2.5 * np.log10(f))

    @property
    def is_conditioned(self) -> bool:
        return len(self._samples) >= self.min_samples

    def reset(self) -> None:
        self._samples.clear()
