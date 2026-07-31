"""Fit the radiometric zero-point model that ``camera_profiles.py`` ships.

Offline calibration support, imported by ``scripts/evaluate_radiometer_archive.py``
and by nothing on the capture path.

The shipped model is

    zero_point = radiometric_zero_point
                 + radiometric_colour_slope * (clamp(R/G) - radiometric_colour_pivot)

so a tool that re-derives only a single constant cannot check it, and would
quietly disagree with the profile on any sensor whose slope is non-zero. These
helpers fit both forms and score them against each other, which is what decides
whether a sensor should carry a colour term at all.

Two things make the comparison honest rather than decorative:

* **Per-sweep, not per-frame.** Frames within a sweep share a sky, an observer
  and a reference reading; pooling them would let a long sweep outvote a whole
  night and shrink every error bar by a factor it has not earned.
* **Leave-one-night-out, not in-sample residuals.** A free parameter always
  reduces in-sample scatter. Only holding out an entire night tests whether the
  colour term *extrapolates* to a sky regime it never saw, which is the claim
  being made. On a sensor where the physics says there is nothing to correct
  (a factory IR-cut leaves almost no NIR leak) this is expected to reject the
  colour model, and that rejection is the control that makes acceptance
  elsewhere meaningful.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np

# A colour fit needs both enough sweeps to constrain two parameters and enough
# spread in R/G to define a slope. Below these the fit is an interpolation
# between two clusters at best, and noise amplification at worst.
MIN_SWEEPS_FOR_COLOUR = 6
MIN_COLOUR_SPREAD = 0.05


@dataclass
class SweepPoint:
    """One sweep reduced to what a zero-point fit needs.

    ``implied_zero_point`` is the constant that would have made this sweep read
    exactly its reference meter, i.e. ``reference - 2.5log10(t) + 2.5log10(F)``.
    Fitting it directly means the fit never has to re-derive the geometry, and
    an error in the fitted zero point is by construction an error in published
    SQM of the same size.
    """

    sweep: str
    night: str
    implied_zero_point: float
    red_over_green: Optional[float] = None


def _sd(values: Sequence[float]) -> float:
    return float(statistics.pstdev(values)) if len(values) > 1 else 0.0


def fit_constant(points: Sequence[SweepPoint]) -> Optional[Dict]:
    """Median implied zero point, and the scatter a constant leaves behind."""
    if not points:
        return None
    zps = [p.implied_zero_point for p in points]
    centre = float(statistics.median(zps))
    return {
        "zero_point": centre,
        "residual_sd": _sd([z - centre for z in zps]),
        "sweeps": len(zps),
    }


def _coloured(points: Sequence[SweepPoint]) -> List[SweepPoint]:
    return [p for p in points if p.red_over_green is not None]


def fit_colour(
    points: Sequence[SweepPoint], pivot: Optional[float] = None
) -> Optional[Dict]:
    """Least-squares zero point against sky colour, expressed about ``pivot``.

    ``pivot`` defaults to the median colour of the sample. Pass the profile's
    pivot when checking a sensor that already ships a colour model; leave it
    None when exploring one that does not, since those profiles carry pivot
    0.0 and an intercept quoted at R/G = 0 is an extrapolation far outside any
    real sky, not a number anyone can compare against.

    Returns None when the sample cannot support two parameters -- too few
    sweeps, or all of them at effectively one colour, where any slope fits.
    """
    usable = _coloured(points)
    if len(usable) < MIN_SWEEPS_FOR_COLOUR:
        return None
    ratios = np.array([p.red_over_green for p in usable], dtype=float)
    zps = np.array([p.implied_zero_point for p in usable], dtype=float)
    lo, hi = float(ratios.min()), float(ratios.max())
    if hi - lo < MIN_COLOUR_SPREAD:
        return None
    if pivot is None:
        pivot = float(np.median(ratios))
    slope, intercept = np.polyfit(ratios - pivot, zps, 1)
    residuals = zps - (intercept + slope * (ratios - pivot))
    return {
        "zero_point_at_pivot": float(intercept),
        "colour_slope": float(slope),
        "pivot": float(pivot),
        "colour_range": [lo, hi],
        "residual_sd": _sd(residuals.tolist()),
        "sweeps": len(usable),
    }


def _predict_colour(model: Dict, ratio: Optional[float], clamp: bool = True) -> float:
    """Zero point for one sweep.

    ``clamp`` mirrors production, which pins R/G to the calibrated range rather
    than extrapolating off the end of the fit. Turning it off answers a
    different question -- see :func:`leave_one_night_out`.
    """
    if ratio is None:
        # No colour on the frame falls back to the pivot value, matching
        # radiometric_sqm's behaviour rather than extrapolating an intercept.
        return model["zero_point_at_pivot"]
    if clamp:
        lo, hi = model["colour_range"]
        ratio = min(max(ratio, lo), hi)
    return model["zero_point_at_pivot"] + model["colour_slope"] * (
        ratio - model["pivot"]
    )


def leave_one_night_out(
    points: Sequence[SweepPoint], pivot: Optional[float] = None
) -> Optional[Dict]:
    """Hold out each night in turn; report MAE for both models.

    An error in predicted zero point is an error in predicted SQM of the same
    size, so these numbers read directly as "how far off would this model have
    been on a night it never saw".

    Colour is scored twice, because two different questions get conflated here
    and they do not have the same answer:

    * ``colour_mae`` clamps to the *training* colour range, so it measures what
      shipping the model would actually have done. When the held-out night is
      the only one of its regime, the clamp pins the prediction at the edge of
      the fitted span and most of the theoretical gain is unavailable.
    * ``colour_mae_unclamped`` lets the fit run past its own range, which is
      the only way to ask whether the physical relation *extrapolates* to an
      unseen regime rather than interpolating between fitted points.

    The verdict uses the clamped figure: it is the conservative one, and it is
    the behaviour that would ship.
    """
    nights = sorted({p.night for p in points})
    if len(nights) < 2:
        return None

    per_night = []
    constant_errors: List[float] = []
    colour_errors: List[float] = []
    colour_errors_unclamped: List[float] = []

    for night in nights:
        train = [p for p in points if p.night != night]
        test = [p for p in points if p.night == night]
        const_model = fit_constant(train)
        colour_model = fit_colour(train, pivot)
        if const_model is None:
            continue

        c_err = [abs(const_model["zero_point"] - p.implied_zero_point) for p in test]
        row = {
            "night": night,
            "sweeps": len(test),
            "constant_mae": float(np.mean(c_err)),
        }
        constant_errors.extend(c_err)
        if colour_model is not None:
            k_err = [
                abs(
                    _predict_colour(colour_model, p.red_over_green)
                    - p.implied_zero_point
                )
                for p in test
            ]
            u_err = [
                abs(
                    _predict_colour(colour_model, p.red_over_green, clamp=False)
                    - p.implied_zero_point
                )
                for p in test
            ]
            row["colour_mae"] = float(np.mean(k_err))
            row["colour_mae_unclamped"] = float(np.mean(u_err))
            # Flags the case above: this night sat outside the training span,
            # so the clamped figure understates what the relation can do.
            row["outside_training_colour_range"] = any(
                p.red_over_green is not None
                and not (
                    colour_model["colour_range"][0]
                    <= p.red_over_green
                    <= colour_model["colour_range"][1]
                )
                for p in test
            )
            colour_errors.extend(k_err)
            colour_errors_unclamped.extend(u_err)
        per_night.append(row)

    if not constant_errors:
        return None
    result = {
        "nights": len(per_night),
        "constant_mae": float(np.mean(constant_errors)),
        "per_night": per_night,
    }
    if colour_errors:
        result["colour_mae"] = float(np.mean(colour_errors))
        result["colour_mae_unclamped"] = float(np.mean(colour_errors_unclamped))
    return result


def evaluate_profile(
    points: Sequence[SweepPoint], pivot: Optional[float] = None
) -> Dict:
    """Fit both models, cross-validate, and say which one the data supports.

    The verdict is deliberately decided by held-out error, not by in-sample
    residual scatter, which the colour model wins by construction.
    """
    constant = fit_constant(points)
    colour = fit_colour(points, pivot)
    cv = leave_one_night_out(points, pivot)

    verdict = "constant"
    reason = "no colour data, or too few sweeps/too little colour spread to fit"
    if colour is None:
        pass
    elif cv is None or "colour_mae" not in cv:
        verdict = "constant"
        reason = "colour model fits, but too few nights to cross-validate it"
    elif cv["colour_mae"] < cv["constant_mae"]:
        verdict = "colour"
        reason = f"held-out MAE {cv['constant_mae']:.3f} -> {cv['colour_mae']:.3f}"
    else:
        reason = (
            f"colour rejected by CV: held-out MAE {cv['constant_mae']:.3f} "
            f"constant vs {cv['colour_mae']:.3f} with colour"
        )

    return {
        "sweeps": len(points),
        "nights": len(sorted({p.night for p in points})),
        "constant": constant,
        "colour": colour,
        "leave_one_night_out": cv,
        "verdict": verdict,
        "verdict_reason": reason,
    }
