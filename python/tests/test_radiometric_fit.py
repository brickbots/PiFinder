"""Tests for the offline radiometric zero-point model fit.

The archive these run against in anger is not in the repo, so the fitting and
cross-validation maths is pinned here on synthetic sweeps whose answer is known
by construction. The point is that the decision "does this sensor need a colour
term" is reproducible, not that any particular archive gives a particular number.
"""

import pytest

from PiFinder.sqm.radiometric_fit import (
    SweepPoint,
    evaluate_profile,
    fit_colour,
    fit_constant,
    leave_one_night_out,
)

PIVOT = 0.85


def _sweeps(spec):
    """Build sweeps from (night, R/G, zero_point) triples."""
    return [
        SweepPoint(
            sweep=f"sweep_{night}_{i:02d}",
            night=night,
            implied_zero_point=zp,
            red_over_green=rg,
        )
        for i, (night, rg, zp) in enumerate(spec)
    ]


def _colour_dependent(slope=5.5, intercept=15.16):
    """Two LP nights and one dark night, zero point linear in sky colour."""
    spec = []
    for night, ratios in (
        ("20260701", [0.83, 0.85, 0.87]),
        ("20260705", [0.84, 0.86, 0.89]),
        ("20260720", [1.00, 1.02, 1.04]),  # the only dark night
    ):
        for rg in ratios:
            spec.append((night, rg, intercept + slope * (rg - PIVOT)))
    return _sweeps(spec)


@pytest.mark.unit
def test_constant_fit_reports_median_and_scatter():
    points = _sweeps([("n1", 0.85, 14.0), ("n1", 0.85, 15.0), ("n2", 0.85, 16.0)])
    fit = fit_constant(points)
    assert fit["zero_point"] == pytest.approx(15.0)
    assert fit["sweeps"] == 3
    assert fit["residual_sd"] > 0


@pytest.mark.unit
def test_colour_fit_recovers_a_known_slope():
    fit = fit_colour(_colour_dependent(slope=5.5, intercept=15.16), PIVOT)
    assert fit["colour_slope"] == pytest.approx(5.5, abs=1e-6)
    assert fit["zero_point_at_pivot"] == pytest.approx(15.16, abs=1e-6)
    assert fit["residual_sd"] == pytest.approx(0.0, abs=1e-9)
    assert fit["colour_range"] == pytest.approx([0.83, 1.04])


@pytest.mark.unit
def test_colour_fit_refuses_a_sample_it_cannot_support():
    """Too few sweeps, or all one colour, must not produce a slope."""
    too_few = _sweeps([("n1", 0.83, 15.0), ("n2", 1.04, 16.0)])
    assert fit_colour(too_few, PIVOT) is None

    # Enough sweeps, but no colour lever arm: any slope fits equally.
    no_spread = _sweeps([("n%d" % i, 0.85, 15.0 + 0.01 * i) for i in range(8)])
    assert fit_colour(no_spread, PIVOT) is None

    mono = [
        SweepPoint(sweep=f"s{i}", night=f"n{i}", implied_zero_point=15.0)
        for i in range(8)
    ]
    assert fit_colour(mono, PIVOT) is None


@pytest.mark.unit
def test_cross_validation_prefers_colour_when_the_sky_really_is_coloured():
    cv = leave_one_night_out(_colour_dependent(), PIVOT)
    assert cv["colour_mae"] < cv["constant_mae"]
    assert cv["nights"] == 3


@pytest.mark.unit
def test_holding_out_the_only_dark_night_tests_extrapolation():
    """The load-bearing case: predict a regime the fit never saw.

    Trained on LP nights alone, the colour model must still land near the dark
    night. A constant cannot -- it can only return the LP average. This is the
    difference between extrapolating and interpolating, and it is the whole
    argument for the colour term being physical rather than a spare parameter.
    """
    cv = leave_one_night_out(_colour_dependent(), PIVOT)
    dark = next(r for r in cv["per_night"] if r["night"] == "20260720")

    # Held out, the dark night's colours sit outside everything the fit saw.
    assert dark["outside_training_colour_range"]

    # Clamped -- what shipping would have done -- the model is pinned at the
    # edge of its fitted span and can only recover part of the gap.
    assert dark["colour_mae"] < dark["constant_mae"]

    # Unclamped, the relation itself extrapolates: on data that is linear by
    # construction it lands essentially exactly, while a constant cannot.
    assert dark["colour_mae_unclamped"] == pytest.approx(0.0, abs=1e-9)
    assert dark["constant_mae"] > 0.5


@pytest.mark.unit
def test_cross_validation_rejects_colour_when_the_sensor_does_not_care():
    """The negative control -- an IR-cut sensor with no NIR leak to correct.

    Colour varies, the zero point does not. In-sample the colour model still
    wins (a free parameter always does), so a verdict taken from residual
    scatter would wrongly ship a slope here. Held-out error is what catches it.
    """
    spec = []
    for night, ratios in (
        ("20260701", [0.83, 0.86, 0.89]),
        ("20260705", [0.90, 0.95, 1.00]),
        ("20260720", [1.00, 1.02, 1.04]),
    ):
        for i, rg in enumerate(ratios):
            # Real scatter, but none of it explained by colour.
            spec.append((night, rg, 14.97 + (0.05 if i % 2 else -0.05)))
    points = _sweeps(spec)

    # Least squares cannot do worse in sample than the no-slope fit, so this
    # comparison can never reject a colour term however useless it is.
    in_sample_colour = fit_colour(points, PIVOT)["residual_sd"]
    in_sample_constant = fit_constant(points)["residual_sd"]
    assert in_sample_colour <= in_sample_constant + 1e-9  # the trap

    result = evaluate_profile(points, PIVOT)
    assert result["verdict"] == "constant"
    assert "rejected by CV" in result["verdict_reason"]


@pytest.mark.unit
def test_verdict_is_colour_for_a_genuinely_colour_dependent_sensor():
    result = evaluate_profile(_colour_dependent(), PIVOT)
    assert result["verdict"] == "colour"
    assert result["colour"]["colour_slope"] == pytest.approx(5.5, abs=1e-6)
    assert result["nights"] == 3


@pytest.mark.unit
def test_a_single_night_cannot_be_cross_validated():
    """One night is not evidence about another night."""
    points = _sweeps([("20260701", 0.83 + 0.03 * i, 15.0 + i) for i in range(7)])
    assert leave_one_night_out(points, PIVOT) is None
    result = evaluate_profile(points, PIVOT)
    assert result["verdict"] == "constant"
    assert "too few nights" in result["verdict_reason"]


@pytest.mark.unit
def test_prediction_clamps_to_the_fitted_colour_range():
    """Never extrapolate off the end of the fit, matching production."""
    from PiFinder.sqm.radiometric_fit import _predict_colour

    model = fit_colour(_colour_dependent(), PIVOT)
    at_top = _predict_colour(model, 1.04)
    assert _predict_colour(model, 5.0) == pytest.approx(at_top)
    at_bottom = _predict_colour(model, 0.83)
    assert _predict_colour(model, 0.1) == pytest.approx(at_bottom)
    # No colour falls back to the pivot value, not the raw intercept.
    assert _predict_colour(model, None) == pytest.approx(model["zero_point_at_pivot"])


@pytest.mark.unit
def test_pivot_defaults_to_the_middle_of_the_measured_colours():
    """Exploring a sensor that ships no colour model must stay interpretable.

    Those profiles carry pivot 0.0, and an intercept quoted at R/G = 0 is an
    extrapolation far outside any real sky. Defaulting to the sample's median
    colour keeps the reported zero point comparable to the shipped constant.
    """
    points = _colour_dependent(slope=5.5, intercept=15.16)
    fit = fit_colour(points)  # no pivot given

    assert fit["pivot"] == pytest.approx(0.87)  # median of the sample colours
    assert fit["colour_slope"] == pytest.approx(5.5, abs=1e-6)
    # Same line, just re-expressed: the value at the explicit pivot is unchanged.
    explicit = fit_colour(points, PIVOT)
    assert fit["zero_point_at_pivot"] == pytest.approx(
        explicit["zero_point_at_pivot"] + 5.5 * (fit["pivot"] - PIVOT), abs=1e-6
    )


@pytest.mark.unit
def test_a_zero_pivot_is_not_silently_used_as_a_real_colour():
    """Guard the wiring the script relies on: `pivot or None` must reach here."""
    points = _colour_dependent()
    assert fit_colour(points, 0.0)["pivot"] == 0.0  # explicit 0.0 is honoured
    assert fit_colour(points, None)["pivot"] != 0.0  # None picks a real colour
