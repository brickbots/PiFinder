"""
Rolling aperture-correction estimate for SQM photometry.

If the lens PSF spills flux beyond the photometry aperture, the fitted
photometric zero point (``mzero``) comes out too low and SQM reads too
bright. Whether and how much flux spills is a property of the optics (focus,
lens halo) and drifts slowly — it is NOT a per-frame quantity, and it is not
measurable per star: a single star's wings sit at or below the sky noise, so
any per-star boundary search integrates noise and reports missing flux even
for a wingless PSF.

So this estimator uses the standard aperture-correction method:

- **Stack**: per frame, median-stack the sky-subtracted, aperture-normalized
  patches of the bright unsaturated matched stars. The stack's SNR grows with
  the number of stars, putting the faint outer profile above the noise.
- **Measure once**: the stack's enclosed-flux curve of growth is normalized
  to the aperture, so its plateau value equals ``total/aperture = 1/f``. The
  plateau is read well outside the aperture (radii 10-16) where any real
  wing flux has been integrated.
- **Smooth** the per-frame samples in a rolling window (median) and apply
  ``-2.5*log10(f)`` to ``mzero`` on every frame.

For optics whose PSF is fully enclosed by the aperture the plateau is 1.0
within noise and the correction is 0 — the estimator degenerates gracefully
instead of inventing wings.
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
        max_radius: int = 20,
        max_samples: int = 20,
        min_samples: int = 3,
        min_stars: int = 5,
        min_peak_snr: float = 8.0,
    ):
        """
        Args:
            aperture_radius: production photometry aperture the correction is for.
            max_radius: patch half-size; sky comes from beyond ``max_radius - 4``.
            max_samples: rolling window of per-frame ``f`` samples.
            min_samples: samples needed before the correction is applied.
            min_stars: per-frame minimum of stacked stars for one ``f`` sample.
            min_peak_snr: star peak must exceed this multiple of the per-pixel
                sky noise to enter the stack (keeps noise out of the median).
        """
        self.aperture_radius = aperture_radius
        self.max_radius = max_radius
        self.max_samples = max_samples
        self.min_samples = min_samples
        self.min_stars = min_stars
        self.min_peak_snr = min_peak_snr
        # Radii at which the growth curve is read as its plateau: far enough
        # out that real wing flux is integrated, well inside the sky region.
        self.plateau_radii = (10, 12, 14, 16)
        self._samples: deque = deque(maxlen=max_samples)

    def add_frame(
        self,
        image: np.ndarray,
        centroids,
        saturation_threshold: float,
    ) -> Optional[float]:
        """
        Measure one frame's enclosed fraction from a bright-star stack.

        Args:
            image: linear photometry image (raw green channel).
            centroids: matched star centroids, (y, x) rows, in `image` pixels.
            saturation_threshold: pixel level above which a star core is skipped.

        Returns:
            The frame's enclosed fraction if measurable, else None.
        """
        if image is None or centroids is None or len(centroids) == 0:
            return None
        height, width = image.shape
        box = self.max_radius
        yy, xx = np.mgrid[-box : box + 1, -box : box + 1]
        r = np.hypot(yy, xx)
        sky_ring = r > (self.max_radius - 4)
        core_zone = r <= 2

        patches = []
        for cy, cx in centroids:
            iy, ix = int(round(cy)), int(round(cx))
            if iy - box < 0 or ix - box < 0 or iy + box >= height or ix + box >= width:
                continue
            patch = image[iy - box : iy + box + 1, ix - box : ix + box + 1].astype(
                np.float64
            )
            if patch[r <= self.aperture_radius].max() >= saturation_threshold:
                continue
            sky = float(np.median(patch[sky_ring]))
            noise = float(np.std(patch[sky_ring]))
            signal = patch - sky
            if signal[core_zone].max() < self.min_peak_snr * max(noise, 1e-3):
                continue
            aperture_flux = float(signal[r <= self.aperture_radius].sum())
            if aperture_flux <= 0:
                continue
            patches.append(signal / aperture_flux)

        if len(patches) < self.min_stars:
            return None

        stack = np.median(np.stack(patches), axis=0)
        plateau = float(np.median([stack[r <= q].sum() for q in self.plateau_radii]))
        if plateau <= 0:
            return None
        f = 1.0 / plateau
        if f >= 1.0 or not np.isfinite(f):
            # Plateau at/below the aperture flux: no measurable spill. Record
            # a clean 1.0 so the window converges to "no correction".
            f = 1.0
        elif f <= 0.2:
            return None  # unphysical; crowding or a corrupted stack

        self._samples.append(f)
        logger.debug(
            "Wing sample f=%.3f from %d stars (window %d)",
            f,
            len(patches),
            len(self._samples),
        )
        return f

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

    def dump(self) -> dict:
        """Full JSON-serializable window state for diagnostics/sweeps."""
        return {
            "enclosed_fraction": self.enclosed_fraction(),
            "correction_mag": self.correction(),
            "is_conditioned": self.is_conditioned,
            "n_samples": len(self._samples),
            "config": {
                "aperture_radius": self.aperture_radius,
                "max_radius": self.max_radius,
                "max_samples": self.max_samples,
                "min_samples": self.min_samples,
                "min_stars": self.min_stars,
                "min_peak_snr": self.min_peak_snr,
                "plateau_radii": list(self.plateau_radii),
            },
            "samples_enclosed_fraction": list(self._samples),
        }

    def reset(self) -> None:
        self._samples.clear()
