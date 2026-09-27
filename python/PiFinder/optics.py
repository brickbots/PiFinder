#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
The optical train: a camera profile paired with the lens fitted in front of it.

Field of view is a property of neither half alone, so nothing that needs it
should carry its own constant. Everything angular PiFinder derives from its
own optics -- the solver's FOV gate, SQM's radiometric field width, the
chart's frustum shading -- comes from here.

The sensor half is auto-detected at startup; the lens half cannot be detected
directly and is whatever the user said is fitted. A wrong *statement* is a
configuration error the device does not, and deliberately will not, discover
for itself: see ``docs/adr/0027-fov-gate-derived-from-optical-train.md``.

When nothing has been stated, though, there is no statement to respect -- only
a fallback. This module keeps the two apart (**stated lens** vs **assumed
lens**, defined in ``docs/ax/camera/CONTEXT.md``), because the solver's FOV
gate is only entitled to narrow around a claim somebody actually made. See
``docs/adr/0029-fov-gate-width-follows-lens-confidence.md``.

Vocabulary is defined in ``docs/ax/camera/CONTEXT.md`` (Optics). In particular
*nominal* focal length is the label on the barrel and *effective* focal length
is what the lens behaves as; only the second is correct to compute with.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from PiFinder.camera_profiles import CameraProfile, get_camera_profile

logger = logging.getLogger("Optics")

# Half-width of the solver's FOV gate, as a fraction of the derived field of
# view. Proportional rather than absolute: a fixed number of degrees is four
# times looser on a 10 degree train than on a 20 degree one. 15% covers
# lens-sample spread, barrel distortion and focus shift, and was validated
# against real frames re-projected to every shipped sensor x lens combination
# with +/-5% lens error injected. It is still tighter than the +/-33% the old
# fixed pair worked out to. See docs/adr/0027.
FOV_GATE_MARGIN = 0.15

# How close a fitted FOV must sit to a lens's derived field of view, as a
# fraction of the latter, before that lens is taken as identified. tetra3 fits
# the field of view to well under a percent, and the candidates on any one
# sensor are ~20% apart (the imx462's are 12.44 and 10.40 degrees), so 5% is
# generous without being ambiguous. Outside it, no lens is named: a third-party
# lens must leave the assumption alone rather than be snapped to the nearest
# thing we happen to sell. See docs/adr/0029.
LENS_IDENTIFY_TOLERANCE = 0.05

# Pixels per side of the image handed to tetra3. Centroids are reported in
# this grid, so it is the grid the solver's plate scale is stated against.
SOLVER_IMAGE_PIXELS = 512

# Sensor to derive angles from when the camera type is one we have no profile
# for. It matches SharedStateObj's pre-camera default, so an unrecognised
# sensor behaves exactly like the window before the camera process reports in
# -- which every consumer here already survives, because it happens on every
# boot.
FALLBACK_CAMERA_TYPE = "imx296"


@dataclass(frozen=True)
class Lens:
    """A finder camera lens (M12 mount).

    Never the user's telescope or eyepiece -- those are Equipment vocabulary
    and carry their own, unrelated focal lengths.
    """

    # Registry key, also the value stored in config under "camera_lens".
    key: str

    # Printed on the barrel. What the user reads and picks from the menu, and
    # the only focal length that should ever appear in the UI.
    nominal_focal_length_mm: float

    # What the lens measures as on-sky. Every derived value uses this one.
    effective_focal_length_mm: float

    # Focal ratio. Not currently load-bearing in any code path -- it is here so
    # that throughput comparisons have somewhere honest to read it from rather
    # than re-deriving it from a front-element measurement, which overstates
    # the aperture (the front element is not the entrance pupil).
    f_number: float

    # Set when the effective focal length is the nominal one standing in for a
    # measurement nobody has made yet, rather than a measured value.
    effective_focal_length_measured: bool = True

    @property
    def menu_label(self) -> str:
        """Short label for the lens menu, e.g. "16mm"."""
        return f"{self.nominal_focal_length_mm:g}mm"


# The lenses PiFinder ships or supports. Keys are stable: they are written to
# user config and must not be renamed without an aliasing path.
LENSES: Dict[str, Lens] = {
    "12mm": Lens(
        key="12mm",
        nominal_focal_length_mm=12.0,
        # 13.04 is what a rev4 imx462 measured on sky: six solves fitting
        # 12.4366 +/- 0.0025 degrees against a 980px @ 2.9um crop. The same
        # board on the 16mm then fitted 10.4011 degrees, reproducing that
        # lens's derived field to 0.02% -- which is what makes this a
        # measurement of the 12mm rather than of the sensor profile. The
        # barrel runs 8.7% long, in the opposite direction from the 16mm's
        # 2.4% short, so neither label predicts the other. See #627.
        effective_focal_length_mm=13.04,
        # Front element measures 9.85mm, but that is not the entrance pupil:
        # M12 front elements are deliberately oversized to accept off-axis
        # rays (the advertised-f/2 16mm shows a 1.24x oversize). Applying the
        # same oversize here rules out f/1.2 -- it would need a pupil larger
        # than the front element -- and f/1.4 would need *less* oversize than
        # the 16mm, which is backwards for a wider lens. The plausible range
        # is f/1.6-f/2.0; 2.0 never over-claims. Settle it by comparing
        # on-sky photometric zero points, not by measuring glass.
        f_number=2.0,
    ),
    "16mm": Lens(
        key="16mm",
        nominal_focal_length_mm=16.0,
        # 15.61 is the single value that reproduces both independently
        # calibrated SQM field widths (imx296 13.71, imx462 10.38) -- two
        # different sensors agreeing on one lens is what makes it a
        # measurement of the lens rather than a fudge factor. Deriving from
        # the nominal 16.0 instead would shift every existing user's SQM by
        # ~0.05 mag.
        effective_focal_length_mm=15.61,
        f_number=2.0,
    ),
    "25mm": Lens(
        key="25mm",
        nominal_focal_length_mm=25.0,
        # Reproduces the HQ's calibrated 10.34 field width to 0.01 degrees.
        effective_focal_length_mm=26.0,
        # Unverified for this lens; the conservative value, same reasoning as
        # the 12mm. Not load-bearing.
        f_number=2.0,
    ),
}


def get_lens(lens_key: str) -> Lens:
    """Look a lens up by registry key.

    Raises:
        ValueError: if the key is not in the registry.
    """
    if lens_key not in LENSES:
        raise ValueError(f"Unknown lens: {lens_key}. Available: {list(LENSES.keys())}")
    return LENSES[lens_key]


def resolve_camera_profile(camera_type: str) -> CameraProfile:
    """The profile to derive angles from, tolerating an unrecognised sensor.

    The sensor half of the train has the same problem the lens half has: the
    live consumers read it from state that a wrong value can reach --
    ``camera_type`` is whatever the camera process published, and it is a
    plain string. Raising there is worse than being approximately right: the
    solver resolves per frame inside a loop whose outer handler restarts the
    whole solver, tetra3 database load included, and the lens menu resolves
    while it is being built. An unknown sensor would be a crash-reload loop
    and an unopenable menu rather than a diagnosis.

    So this is the one place the fallback policy lives -- the counterpart of
    ``resolve_lens`` for the other half. ``get_camera_profile`` stays strict:
    offline scripts and tests naming a sensor should still hear about a typo.
    """
    try:
        return get_camera_profile(camera_type)
    except ValueError:
        logger.warning(
            "Unknown camera type %r; deriving optics from %s instead",
            camera_type,
            FALLBACK_CAMERA_TYPE,
        )
        return get_camera_profile(FALLBACK_CAMERA_TYPE)


def lens_is_stated(lens_key: Optional[str]) -> bool:
    """True when config names a lens we recognise -- a claim, not a fallback.

    The predicate ``resolve_lens`` decides on, exposed separately because the
    *fact of having been told* outlives the resolution: the FOV gate widens
    when this is false, and self-heal only ever writes into that case. An
    unrecognised key counts as unstated -- it resolves to the fallback, so
    treating it as a claim would gate tightly around a lens nobody named.
    """
    return bool(lens_key) and lens_key in LENSES


def resolve_lens(profile: CameraProfile, lens_key: Optional[str] = None) -> Lens:
    """The lens to use for a profile, given what the config says (if anything).

    An absent or unrecognised key falls back to the sensor's assumed lens.
    That fallback is what lets installs predating the lens setting resolve
    correctly with no migration, and it keeps a hand-edited config from
    breaking every derived angle.
    """
    if lens_is_stated(lens_key):
        return LENSES[str(lens_key)]
    return get_lens(profile.default_lens_key)


@dataclass(frozen=True)
class OpticalTrain:
    """A camera profile paired with the lens in front of it.

    The unit that has a field of view. Neither half has one on its own.
    """

    profile: CameraProfile
    lens: Lens

    # Whether ``lens`` was stated in config or merely assumed. Only the FOV
    # gate reads it: every other derived angle uses the resolved lens either
    # way, because an assumption is still the best available answer. See
    # :meth:`solver_fov_params`.
    lens_stated: bool = False

    @property
    def fov_degrees(self) -> float:
        """Edge-to-edge angular width of the crop, in degrees.

        Not the diagonal. Computed from the *effective* focal length.
        """
        width_px, _height_px = self.profile.crop_size
        width_mm = width_px * self.profile.pixel_pitch_um / 1000.0
        half_angle = math.atan2(width_mm / 2.0, self.lens.effective_focal_length_mm)
        return math.degrees(half_angle) * 2.0

    def plate_scale_arcsec(self, pixels_per_side: int) -> float:
        """Angular size of one pixel, in arcsec, on a named pixel grid.

        The grid has to be named: the 512-pixel solver image and the native
        crop differ by the downscale factor, and confusing them silently
        rescales any angle computed from the result.
        """
        if pixels_per_side <= 0:
            raise ValueError("pixels_per_side must be positive")
        return self.fov_degrees * 3600.0 / pixels_per_side

    @property
    def native_plate_scale_arcsec(self) -> float:
        """Plate scale on the native crop."""
        return self.plate_scale_arcsec(self.profile.crop_size[0])

    @property
    def solver_plate_scale_arcsec(self) -> float:
        """Plate scale on the 512x512 image handed to tetra3."""
        return self.plate_scale_arcsec(SOLVER_IMAGE_PIXELS)

    def solver_fov_params(self) -> Tuple[float, float]:
        """``(fov_estimate, fov_max_error)`` for tetra3 -- the FOV gate.

        tetra3 enforces this window twice: candidate patterns whose implied
        field of view falls outside are discarded before verification, and any
        survivor is rejected after fitting. A frame whose true field of view
        lies outside does not solve at all, however many centroids it has.
        ``fov_max_error`` is an absolute angle, not a fraction, so the margin
        is multiplied out here.

        The width follows what is actually known about the lens. A **stated**
        lens is a claim, so the gate narrows around the single field of view
        it implies. An **assumed** lens is not a claim, so the gate spans
        every lens this sensor has shipped with -- and then ``fov_estimate``
        is no longer this device's field of view but the centre of a plausible
        range, which is why the pair only means anything read together.
        Widening costs essentially nothing in solve time while keeping the
        upper bound that rejects confident mis-solves; over-tightening costs
        the whole ``solve_timeout`` on every frame, forever. See ADR 0029.
        """
        candidates = self.profile.shipped_lens_keys or (self.lens.key,)
        if self.lens_stated or len(candidates) == 1:
            # Either somebody named the lens, or the sensor only ever shipped
            # one and there is nothing an assumption could be wrong about. The
            # second case is why the HQ's gate is unchanged by ADR 0029 --
            # and it is spelled out rather than left to fall out of the union
            # below, which would re-derive the same window through different
            # arithmetic and land a float ULP away from the value that has
            # been shipping.
            fov = self.fov_degrees
            return fov, fov * FOV_GATE_MARGIN

        # tetra3's window is symmetric, so the union of the per-lens windows
        # has to be re-centred rather than handed over as a pair of bounds.
        bounds = [
            OpticalTrain(self.profile, get_lens(key), lens_stated=True).fov_degrees
            for key in candidates
        ]
        low = min(bound * (1.0 - FOV_GATE_MARGIN) for bound in bounds)
        high = max(bound * (1.0 + FOV_GATE_MARGIN) for bound in bounds)
        return (low + high) / 2.0, (high - low) / 2.0

    def __repr__(self) -> str:
        return (
            f"OpticalTrain({self.profile.crop_size[0]}px @ "
            f"{self.profile.pixel_pitch_um}um x {self.lens.key}, "
            f"fov={self.fov_degrees:.2f}deg)"
        )


def identify_lens_from_fitted_fov(
    profile: CameraProfile, fitted_fov_degrees: Optional[float]
) -> Optional[str]:
    """Which shipped lens a measured field of view implies, if any.

    The lens half of the train is not detectable directly, but it is not
    unknowable: a **fitted FOV** measures the train as a whole, and the sensor
    half is known, so what is left is the lens. This is that division, done by
    comparison rather than by algebra -- the answer has to be a registry key,
    since ``camera_lens`` is a key and the Lens menu renders it.

    Candidates are restricted to the lenses this sensor has shipped with,
    which is self-consistent: those are the only lenses the assumed-lens gate
    could have admitted a solve for in the first place.

    Returns None when nothing lands within :data:`LENS_IDENTIFY_TOLERANCE` --
    the honest answer for third-party glass, and the reason this cannot snap a
    measurement to a lens the device does not actually have.
    """
    if not fitted_fov_degrees or fitted_fov_degrees <= 0.0:
        return None

    best_key: Optional[str] = None
    best_error: Optional[float] = None
    for key in profile.shipped_lens_keys:
        derived = OpticalTrain(profile, get_lens(key), lens_stated=True).fov_degrees
        error = abs(fitted_fov_degrees - derived) / derived
        if best_error is None or error < best_error:
            best_key, best_error = key, error

    if best_error is None or best_error > LENS_IDENTIFY_TOLERANCE:
        return None
    return best_key


def optical_train_for_profile(
    profile: CameraProfile, lens_key: Optional[str] = None
) -> OpticalTrain:
    """Pair an already-loaded profile with the stated (or assumed) lens."""
    return OpticalTrain(
        profile=profile,
        lens=resolve_lens(profile, lens_key),
        lens_stated=lens_is_stated(lens_key),
    )


def build_optical_train(
    camera_type: str, lens_key: Optional[str] = None
) -> OpticalTrain:
    """Resolve a full optical train from a camera type and a config value.

    Args:
        camera_type: profile name as detected by the camera process
            ("imx296", "imx462", "imx290", "hq").
        lens_key: the ``camera_lens`` config value, or None when unset.
    """
    return optical_train_for_profile(get_camera_profile(camera_type), lens_key)


class OpticalTrainResolver:
    """Caches the resolved train, rebuilding it when either half changes.

    The lens is re-read live rather than latched at process start so that
    changing it takes effect on the next frame instead of the next boot, but
    rebuilding a train per frame would re-copy a profile for no reason. Keyed
    on both halves because the camera type is also not final at startup: it
    still holds the pre-camera default until the camera process reports.

    Neither half raises on an unrecognised value: both resolve through the
    fallbacks above. Caching under the *stated* key rather than the resolved
    one is what keeps an unknown sensor from logging once per frame, and it
    keeps the identity of the returned train stable so callers can compare
    trains with ``is`` to detect a real change.
    """

    def __init__(self) -> None:
        self._key: Optional[Tuple[str, Optional[str]]] = None
        self._train: Optional[OpticalTrain] = None

    def resolve(self, camera_type: str, lens_key: Optional[str] = None) -> OpticalTrain:
        key = (camera_type, lens_key)
        if key != self._key or self._train is None:
            self._train = optical_train_for_profile(
                resolve_camera_profile(camera_type), lens_key
            )
            self._key = key
        return self._train
