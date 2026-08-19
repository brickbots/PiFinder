"""Tests for the optical train: camera profile x lens -> derived angles.

The point of these is that field of view stopped being three hard-coded
constants and became one computed value. So most of what is worth asserting is
that the computation *reproduces* the measurements the constants came from --
if it does not, this change silently moved everyone's SQM and everyone's FOV
gate. See docs/adr/0027-fov-gate-derived-from-optical-train.md.
"""

import logging
import math

import pytest

from PiFinder.camera_profiles import CAMERA_PROFILES, get_camera_profile
from PiFinder.optics import (
    FALLBACK_CAMERA_TYPE,
    FOV_GATE_MARGIN,
    LENS_IDENTIFY_TOLERANCE,
    LENSES,
    SOLVER_IMAGE_PIXELS,
    Lens,
    OpticalTrain,
    OpticalTrainResolver,
    build_optical_train,
    get_lens,
    identify_lens_from_fitted_fov,
    lens_is_stated,
    optical_train_for_profile,
    resolve_camera_profile,
    resolve_lens,
)


# The radiometric field widths that shipped as per-sensor constants, each
# independently calibrated against a reference meter. They are the ground
# truth this module's arithmetic has to land on; they are written here rather
# than read from the profiles precisely because the profiles no longer carry
# them.
SHIPPED_RADIOMETRIC_FIELD_WIDTHS = {
    "imx296": 13.71,
    "imx462": 10.38,
    "imx290": 10.38,
    "hq": 10.34,
}

# Tolerance on reproducing those constants. 0.03 degrees on a ~10 degree field
# is 0.3% in width, so 0.6% in solid angle, so under 0.01 mag of SQM -- an
# order of magnitude below the ~0.05 mag error that deriving from the nominal
# 16.0 focal length would have introduced, and two below the sweep-to-sweep
# scatter of the calibrations themselves.
FIELD_WIDTH_TOLERANCE_DEG = 0.03


@pytest.mark.unit
class TestLensRegistry:
    """The lens half of the train."""

    def test_keys_are_self_consistent(self):
        for key, lens in LENSES.items():
            assert lens.key == key

    def test_menu_label_reads_off_the_barrel(self):
        # The label must be the nominal focal length: it is what the user
        # compares against the marking on the lens.
        assert LENSES["16mm"].menu_label == "16mm"
        assert LENSES["16mm"].nominal_focal_length_mm == 16.0

    def test_sixteen_mm_computes_with_its_measured_length(self):
        # Nominal and effective genuinely differ, and only the effective one
        # is correct to compute with. If these ever collapse to one value,
        # every derived angle moves.
        lens = LENSES["16mm"]
        assert lens.effective_focal_length_mm == pytest.approx(15.61)
        assert lens.nominal_focal_length_mm != lens.effective_focal_length_mm

    def test_no_effective_length_is_standing_in_for_a_measurement(self):
        # The 12mm carried its nominal 12.0 as a placeholder until a rev4
        # imx462 measured it on sky at 13.04mm (#627), and it was 8.7% out.
        # Nothing in the registry stands in for a measurement now; anything
        # added that does has to say so in the data, not just in a comment,
        # or it gets quietly treated as calibrated the same way.
        for key, lens in LENSES.items():
            assert lens.effective_focal_length_measured is True, key

    def test_unknown_lens_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown lens"):
            get_lens("8mm")


@pytest.mark.unit
class TestDerivedFieldOfView:
    """The derivation, checked against what was actually measured on-sky."""

    @pytest.mark.parametrize(
        "camera_type,expected", sorted(SHIPPED_RADIOMETRIC_FIELD_WIDTHS.items())
    )
    def test_reproduces_the_calibrated_radiometric_field_widths(
        self, camera_type, expected
    ):
        """Deriving must not move the SQM of a single existing user.

        Each of these was calibrated separately against a reference meter, on
        different sensors, at different sites. One effective focal length per
        lens reproducing all of them is what makes the derivation a
        measurement of the optics rather than a curve fit.
        """
        derived = build_optical_train(camera_type).fov_degrees
        assert derived == pytest.approx(expected, abs=FIELD_WIDTH_TOLERANCE_DEG)

    def test_sixteen_mm_is_pinned_by_two_independent_sensors(self):
        # The 15.61 effective length is only credible because two different
        # sensors with different pitches and different crops agree on it.
        # Assert that agreement directly: it is the evidence, not a detail.
        for camera_type in ("imx296", "imx462"):
            derived = build_optical_train(camera_type, "16mm").fov_degrees
            assert derived == pytest.approx(
                SHIPPED_RADIOMETRIC_FIELD_WIDTHS[camera_type],
                abs=FIELD_WIDTH_TOLERANCE_DEG,
            )

    def test_nominal_focal_length_would_have_shifted_sqm(self):
        """Guards the choice of effective over nominal, not just its value.

        Swapping in the nominal 16.0 changes the assumed solid angle, which
        biases every published radiometric SQM. Show that the error this
        avoids is real and larger than the tolerance above.
        """
        profile = get_camera_profile("imx296")
        nominal_lens = Lens(
            key="16mm-nominal",
            nominal_focal_length_mm=16.0,
            effective_focal_length_mm=16.0,
            f_number=2.0,
        )
        effective = build_optical_train("imx296", "16mm").fov_degrees
        nominal = OpticalTrain(profile=profile, lens=nominal_lens).fov_degrees

        assert abs(nominal - effective) > FIELD_WIDTH_TOLERANCE_DEG
        # Solid angle scales as width squared, so the magnitude offset is
        # 5*log10 of the width ratio: ~0.05 mag, as the ADR states. The
        # nominal length is the longer one, so it understates the field and
        # reads the sky brighter -- hence the negative sign.
        mag_shift = 5.0 * math.log10(nominal / effective)
        assert mag_shift == pytest.approx(-0.05, abs=0.01)

    def test_twelve_mm_on_imx296_falls_outside_the_old_fixed_window(self):
        """The combination that motivated the whole change.

        The retired constants were fov_estimate=12.0, fov_max_error=4.0, i.e.
        a [8.0, 16.0] window. A 12mm lens on an imx296 images ~16.4 degrees
        and could not solve at all. The margin narrowed when the 12mm's
        effective length was measured (#627) -- 17.8 degrees was derived from
        the nominal -- but it did not close.
        """
        fov = build_optical_train("imx296", "12mm").fov_degrees
        assert fov == pytest.approx(16.38, abs=0.05)
        assert fov > 16.0

    def test_field_of_view_is_the_crop_not_the_raw_sensor(self):
        # PiFinder images a square crop out of a wider sensor. Deriving from
        # raw_size would overstate every angle.
        profile = get_camera_profile("imx296")
        assert profile.crop_size == (1088, 1088)
        assert profile.crop_size[0] < profile.raw_size[0]

    def test_longer_lens_narrows_the_field(self):
        profile = get_camera_profile("imx296")
        widths = [
            optical_train_for_profile(profile, key).fov_degrees
            for key in ("12mm", "16mm", "25mm")
        ]
        assert widths == sorted(widths, reverse=True)


@pytest.mark.unit
class TestFovGate:
    """What the solver is actually handed."""

    def test_gate_is_centred_on_the_derived_field_of_view(self):
        train = build_optical_train("imx296", "16mm")
        estimate, max_error = train.solver_fov_params()
        assert estimate == pytest.approx(train.fov_degrees)
        assert max_error == pytest.approx(train.fov_degrees * FOV_GATE_MARGIN)

    def test_margin_is_proportional_not_absolute(self):
        # An absolute margin is proportionally looser on a narrow train than a
        # wide one, which is the reason for the choice.
        narrow = build_optical_train("imx462", "25mm").solver_fov_params()
        wide = build_optical_train("hq", "12mm").solver_fov_params()
        assert wide[1] > narrow[1]
        assert wide[1] / wide[0] == pytest.approx(narrow[1] / narrow[0])

    def test_gate_is_tighter_than_the_constants_it_replaced(self):
        # The retired pair worked out to +/-33%. Deriving is more correct
        # *and* more selective, which is the claim the ADR makes.
        assert FOV_GATE_MARGIN < 4.0 / 12.0

    def test_shipped_trains_sit_inside_the_pattern_database_range(self):
        """Every default combination must be solvable with the shipped DB.

        The bundled database is built for 10-30 degrees. A default that fell
        outside would mean a device that never solves out of the box, and no
        rebuild is planned as part of this change.
        """
        for camera_type in CAMERA_PROFILES:
            estimate, max_error = build_optical_train(camera_type).solver_fov_params()
            assert estimate - max_error < 30.0
            assert estimate + max_error > 10.0


# The assumed-lens gates from the table in ADR 0029, as (low, high) degrees.
# Written out rather than recomputed: the point of the table is that these
# specific windows were reasoned about, in particular that the imx462's lands
# within a whisker of the pre-0027 [8.0, 16.0] these units are known to work
# under, and that the hq's does not move at all.
# Recomputed after the 12mm's effective focal length was measured at 13.04mm
# (#627); the ADR's original table derived the 12mm's field from its nominal.
# The upper bounds moved down with it, the hq is untouched because it never
# shipped a 12mm, and every gate still spans both of its sensor's lenses --
# which is the property test_the_assumed_gate_spans_every_lens_the_sensor
# _shipped checks independently of these numbers.
ADR_0029_ASSUMED_GATES = {
    "imx296": (11.65, 18.84),
    "imx462": (8.84, 14.30),
    "imx290": (8.84, 14.30),
    "hq": (8.78, 11.88),
}

# The gate the hq has been shipping. Self-heal and the union arithmetic must
# not perturb it by so much as a float ULP -- the hq only ever shipped one
# lens, so nothing about it is supposed to widen.
HQ_SHIPPED_GATE = (10.328372829303238, 1.5492559243954855)


@pytest.mark.unit
class TestLensIsStated:
    """The distinction the whole of ADR 0029 turns on."""

    def test_a_registered_key_is_a_statement(self):
        assert lens_is_stated("16mm") is True
        assert lens_is_stated("12mm") is True

    def test_absence_is_not_a_statement(self):
        assert lens_is_stated(None) is False
        assert lens_is_stated("") is False

    def test_an_unrecognised_key_is_not_a_statement(self):
        # It resolves to the fallback, so treating it as a claim would gate
        # tightly around a lens nobody named -- the exact failure mode ADR
        # 0029 exists to remove.
        assert lens_is_stated("40mm") is False

    def test_it_is_the_predicate_resolve_lens_already_used(self):
        # Not a second, drifting definition of "recognised".
        profile = get_camera_profile("imx296")
        for key in (None, "", "40mm", "16mm", "12mm"):
            resolved_is_the_key = resolve_lens(profile, key).key == key
            assert resolved_is_the_key == lens_is_stated(key), key


@pytest.mark.unit
class TestAssumedLensGate:
    """ADR 0029: the gate widens exactly when nobody stated a lens."""

    @pytest.mark.parametrize(
        "camera_type,expected", sorted(ADR_0029_ASSUMED_GATES.items())
    )
    def test_assumed_gate_matches_the_adr_table(self, camera_type, expected):
        estimate, max_error = build_optical_train(camera_type, None).solver_fov_params()
        low, high = estimate - max_error, estimate + max_error
        assert (round(low, 2), round(high, 2)) == expected

    def test_the_assumed_gate_spans_every_lens_the_sensor_shipped(self):
        """The property the table is an instance of.

        A unit with no stated lens must be able to solve on any lens it could
        have come out of the box with -- that is the whole fix.
        """
        for camera_type, profile in CAMERA_PROFILES.items():
            estimate, max_error = build_optical_train(
                camera_type, None
            ).solver_fov_params()
            for key in profile.shipped_lens_keys:
                fov = build_optical_train(camera_type, key).fov_degrees
                assert estimate - max_error <= fov <= estimate + max_error, (
                    camera_type,
                    key,
                )

    def test_a_stated_lens_keeps_the_narrow_gate(self):
        # 0027's benefit is untouched for anyone who said what they have.
        for camera_type in CAMERA_PROFILES:
            for key in ("12mm", "16mm", "25mm"):
                train = build_optical_train(camera_type, key)
                estimate, max_error = train.solver_fov_params()
                assert estimate == pytest.approx(train.fov_degrees)
                assert max_error == pytest.approx(train.fov_degrees * FOV_GATE_MARGIN)

    def test_widening_does_not_move_the_derived_field_of_view(self):
        """Only the gate widens. SQM and the frustum must not move.

        They stay approximate under an assumed lens until self-heal corrects
        it -- which is the point of self-heal, not a defect in the gate.
        """
        for camera_type, profile in CAMERA_PROFILES.items():
            assumed = build_optical_train(camera_type, None)
            assert assumed.fov_degrees == pytest.approx(
                build_optical_train(camera_type, profile.default_lens_key).fov_degrees
            )

    def test_the_hq_gate_is_bit_identical_to_what_shipped(self):
        """The hq only ever shipped one lens, so it has nothing to widen to.

        Asserted on the exact floats, not approximately: any movement here
        means the union arithmetic leaked into a sensor it has no business
        touching.
        """
        assert build_optical_train("hq", None).solver_fov_params() == HQ_SHIPPED_GATE
        assert build_optical_train("hq", "25mm").solver_fov_params() == HQ_SHIPPED_GATE

    def test_an_imx462_with_no_stated_lens_admits_a_twelve_mm_frame(self):
        """The regression, stated as a test.

        A rev4 that shipped with the 12mm and no config assumed the 16mm,
        gated [8.84, 11.96], and rejected its own 12.44 degree frames -- every
        one of them, having changed nothing. (The ADR says 13.51 there: that
        was derived from the 12mm's nominal length, before #627 measured it.
        The frames were always 12.44 degrees wide, and always outside.)
        """
        fitted = build_optical_train("imx462", "12mm").fov_degrees
        assert fitted == pytest.approx(12.44, abs=0.05)

        estimate, max_error = build_optical_train("imx462", "16mm").solver_fov_params()
        assert fitted > estimate + max_error  # the bug

        estimate, max_error = build_optical_train("imx462", None).solver_fov_params()
        assert estimate - max_error < fitted < estimate + max_error  # the fix

    def test_the_assumed_gate_still_rejects_a_wild_field_of_view(self):
        """Why this is a union and not "drop the hint".

        With injected noise, wide and hintless gates returned *confident*
        false solves at 20-23 degrees that match_threshold did not reject. The
        upper bound is what catches those, so it has to stay finite.
        """
        estimate, max_error = build_optical_train("imx462", None).solver_fov_params()
        assert estimate + max_error < 16.0

    def test_widening_is_bounded_by_the_lenses_we_actually_ship(self):
        # Not a bigger constant margin: the assumed gate is only as wide as
        # the hardware makes it, so a sensor with one lens gets no slack.
        for camera_type, profile in CAMERA_PROFILES.items():
            _, assumed_error = build_optical_train(
                camera_type, None
            ).solver_fov_params()
            _, stated_error = build_optical_train(
                camera_type, profile.default_lens_key
            ).solver_fov_params()
            if len(profile.shipped_lens_keys) == 1:
                assert assumed_error == stated_error, camera_type
            else:
                assert assumed_error > stated_error, camera_type


@pytest.mark.unit
class TestShippedLensKeys:
    """The set the assumed gate spans and self-heal identifies within."""

    def test_the_assumed_lens_is_one_of_the_shipped_ones(self):
        # Asserted here rather than at import: a profile whose fallback is not
        # in its own shipped set would gate around a lens the union excludes.
        for camera_type, profile in CAMERA_PROFILES.items():
            assert profile.default_lens_key in profile.shipped_lens_keys, camera_type

    def test_every_shipped_key_is_a_registered_lens(self):
        for camera_type, profile in CAMERA_PROFILES.items():
            assert profile.shipped_lens_keys, camera_type
            for key in profile.shipped_lens_keys:
                assert key in LENSES, (camera_type, key)

    def test_the_sensors_that_shipped_two_lenses_say_so(self):
        # The 12mm rev4 units are the reason this field exists.
        for camera_type in ("imx296", "imx462", "imx290"):
            assert set(get_camera_profile(camera_type).shipped_lens_keys) == {
                "16mm",
                "12mm",
            }
        assert get_camera_profile("hq").shipped_lens_keys == ("25mm",)


@pytest.mark.unit
class TestIdentifyLensFromFittedFov:
    """Dividing the sensor back out of a measured field of view."""

    def test_identifies_each_lens_from_its_own_derived_field(self):
        for camera_type, profile in CAMERA_PROFILES.items():
            for key in profile.shipped_lens_keys:
                fitted = build_optical_train(camera_type, key).fov_degrees
                assert identify_lens_from_fitted_fov(profile, fitted) == key

    def test_tolerates_a_realistic_fit_error(self):
        # tetra3 fits to well under a percent; the debug frames measure ~10.2
        # against the hq's derived 10.33, which is ~1% out and must identify.
        profile = get_camera_profile("hq")
        assert identify_lens_from_fitted_fov(profile, 10.2) == "25mm"

    def test_third_party_glass_names_no_lens(self):
        # The honest answer. A wrong write is worse than none: the gate would
        # tighten around it and the device could no longer measure its way out.
        profile = get_camera_profile("imx462")
        assert identify_lens_from_fitted_fov(profile, 20.0) is None
        assert identify_lens_from_fitted_fov(profile, 7.0) is None

    def test_the_tolerance_boundary_is_where_it_says_it_is(self):
        profile = get_camera_profile("imx462")
        derived = build_optical_train("imx462", "12mm").fov_degrees
        just_inside = derived * (1.0 + LENS_IDENTIFY_TOLERANCE * 0.9)
        just_outside = derived * (1.0 + LENS_IDENTIFY_TOLERANCE * 1.1)
        assert identify_lens_from_fitted_fov(profile, just_inside) == "12mm"
        assert identify_lens_from_fitted_fov(profile, just_outside) is None

    def test_the_candidates_are_far_enough_apart_to_be_unambiguous(self):
        """5% is only generous because the lenses are ~30% apart.

        If a future lens landed inside another's tolerance, the nearest-match
        rule would start guessing. Catch that here rather than on a device.
        """
        for camera_type, profile in CAMERA_PROFILES.items():
            fields = [
                build_optical_train(camera_type, key).fov_degrees
                for key in profile.shipped_lens_keys
            ]
            for i, a in enumerate(fields):
                for b in fields[i + 1 :]:
                    separation = abs(a - b) / min(a, b)
                    assert separation > 2 * LENS_IDENTIFY_TOLERANCE, camera_type

    def test_only_shipped_lenses_are_candidates(self):
        # The hq's 16mm field is 17.12 degrees, but the hq never shipped one,
        # so a frame measuring that identifies nothing rather than the 16mm.
        profile = get_camera_profile("hq")
        assert build_optical_train("hq", "16mm").fov_degrees == pytest.approx(
            17.12, abs=0.05
        )
        assert identify_lens_from_fitted_fov(profile, 17.12) is None

    def test_a_missing_or_impossible_measurement_names_no_lens(self):
        profile = get_camera_profile("imx462")
        assert identify_lens_from_fitted_fov(profile, None) is None
        assert identify_lens_from_fitted_fov(profile, 0.0) is None
        assert identify_lens_from_fitted_fov(profile, -10.0) is None


@pytest.mark.unit
class TestPlateScale:
    """Plate scale is meaningless without naming the pixel grid."""

    def test_solver_and_native_grids_differ(self):
        train = build_optical_train("imx296", "16mm")
        assert train.solver_plate_scale_arcsec != train.native_plate_scale_arcsec
        # imx296's crop is larger than the solve image, so its native pixels
        # subtend less sky than the solver's.
        assert train.native_plate_scale_arcsec < train.solver_plate_scale_arcsec

    def test_scale_spans_the_whole_field(self):
        train = build_optical_train("imx296", "16mm")
        total = train.solver_plate_scale_arcsec * SOLVER_IMAGE_PIXELS
        assert total == pytest.approx(train.fov_degrees * 3600.0)

    def test_rejects_a_meaningless_grid(self):
        with pytest.raises(ValueError):
            build_optical_train("imx296").plate_scale_arcsec(0)


@pytest.mark.unit
class TestZeroMigration:
    """Configs written before the lens setting existed must still be right."""

    def test_every_profile_names_a_registered_default_lens(self):
        for camera_type, profile in CAMERA_PROFILES.items():
            assert profile.default_lens_key in LENSES, camera_type

    def test_defaults_match_what_each_build_shipped_with(self):
        assert get_camera_profile("hq").default_lens_key == "25mm"
        for camera_type in ("imx296", "imx462", "imx290"):
            assert get_camera_profile(camera_type).default_lens_key == "16mm"

    def test_unset_config_resolves_to_the_shipped_lens(self):
        for camera_type, profile in CAMERA_PROFILES.items():
            assert resolve_lens(profile, None).key == profile.default_lens_key

    def test_unrecognised_config_value_falls_back_rather_than_raising(self):
        # A hand-edited or downgraded config must not take the solver down
        # with it; the shipped lens is the safe reading of "unknown".
        profile = get_camera_profile("imx296")
        assert resolve_lens(profile, "40mm").key == "16mm"
        assert resolve_lens(profile, "").key == "16mm"

    def test_an_unset_config_reproduces_the_pre_change_sqm(self):
        # The whole point of the default: an existing install that never
        # touches the new setting sees the same field width it always did.
        for camera_type, expected in SHIPPED_RADIOMETRIC_FIELD_WIDTHS.items():
            train = build_optical_train(camera_type, None)
            assert train.fov_degrees == pytest.approx(
                expected, abs=FIELD_WIDTH_TOLERANCE_DEG
            )


@pytest.mark.unit
class TestOpticalTrainResolver:
    """Live re-read, so a lens change lands without a restart."""

    def test_reuses_the_train_while_both_halves_hold(self):
        resolver = OpticalTrainResolver()
        first = resolver.resolve("imx296", "16mm")
        assert resolver.resolve("imx296", "16mm") is first

    def test_rebuilds_when_the_lens_changes(self):
        resolver = OpticalTrainResolver()
        before = resolver.resolve("imx296", "16mm")
        after = resolver.resolve("imx296", "12mm")
        assert after is not before
        assert after.fov_degrees != before.fov_degrees

    def test_rebuilds_when_the_camera_is_detected(self):
        # Startup order matters: the solver sees the pre-camera default first
        # and the real sensor only once the camera process reports.
        resolver = OpticalTrainResolver()
        before = resolver.resolve("imx296", None)
        after = resolver.resolve("hq", None)
        assert after is not before
        assert after.lens.key == "25mm"

    def test_unset_lens_is_distinct_from_a_stated_one(self):
        resolver = OpticalTrainResolver()
        unset = resolver.resolve("imx296", None)
        stated = resolver.resolve("imx296", "16mm")
        # Same optics either way, but they are different cache entries -- the
        # resolver must not treat None as already-resolved.
        assert stated is not unset
        assert stated.fov_degrees == pytest.approx(unset.fov_degrees)

    def test_unknown_sensor_falls_back_rather_than_raising(self):
        # The solver resolves inside a per-frame loop whose outer handler
        # restarts the solver, tetra3 database load included. A ValueError
        # here is a crash-reload loop once per frame, not a diagnosis.
        resolver = OpticalTrainResolver()
        train = resolver.resolve("none", None)
        assert train.fov_degrees == pytest.approx(
            build_optical_train(FALLBACK_CAMERA_TYPE).fov_degrees
        )

    def test_the_fallback_is_cached_so_it_logs_once(self, caplog):
        # Cached under the *stated* key: that is what turns once-per-frame
        # logging into once-per-change, and it keeps the returned train
        # identical so callers comparing with `is` see no spurious change.
        resolver = OpticalTrainResolver()
        with caplog.at_level(logging.WARNING, logger="Optics"):
            first = resolver.resolve("none", None)
            again = resolver.resolve("none", None)
        assert again is first
        assert len(caplog.records) == 1

    def test_a_real_sensor_still_rebuilds_after_a_fallback(self):
        # The actual startup sequence: whatever the camera process publishes
        # first must not be latched in place of the sensor it later reports.
        resolver = OpticalTrainResolver()
        fallback = resolver.resolve("none", None)
        detected = resolver.resolve("hq", None)
        assert detected is not fallback
        assert detected.lens.key == "25mm"
        assert detected.fov_degrees == pytest.approx(
            build_optical_train("hq").fov_degrees
        )


@pytest.mark.unit
class TestCameraProfileFallback:
    """The sensor half of "resolve, don't raise", shared by every consumer."""

    def test_known_sensors_resolve_to_themselves(self):
        for camera_type in CAMERA_PROFILES:
            assert resolve_camera_profile(camera_type) == get_camera_profile(
                camera_type
            )

    def test_unknown_sensor_resolves_to_the_shared_state_default(self):
        # Matching SharedStateObj's pre-camera default is the point: an
        # unrecognised sensor then behaves like the window every boot already
        # passes through, rather than like a new state nothing has handled.
        assert resolve_camera_profile("none") == get_camera_profile(
            FALLBACK_CAMERA_TYPE
        )

    def test_the_strict_lookup_stays_strict(self):
        # Scripts and tests naming a sensor should still hear about a typo;
        # only the live consumers want the fallback.
        with pytest.raises(ValueError):
            get_camera_profile("none")


@pytest.mark.unit
class TestDebugCameraProfile:
    """Decision 10: the debug camera declares hq, and it is load-bearing."""

    def test_debug_camera_declares_hq(self):
        from PiFinder.camera_debug import CameraDebug

        # get_cam_type() is "<source> <profile>"; camera_interface splits on
        # the space and publishes the second word as the camera type. Go
        # through the real object so the assertion pins the string that ships.
        camera = CameraDebug(exposure_time=1000)
        assert camera.get_cam_type().split(" ")[1].lower() == "hq"

    def test_the_debug_frames_field_of_view_sits_inside_the_hq_gate(self):
        """The frames in test_images/ measure ~10.2 degrees when solved.

        That is inside hq + 25mm's window and outside imx296 + 16mm's, which
        is why the debug camera's declared sensor changed under ADR 0027.

        It is no longer what makes `--camera debug` solve, though, and reading
        it that way is how the regression got missed: this fits only because
        no lens is stated. State one and the same sensor derives 17.12 or
        20.43 degrees. The gate is now omitted entirely under an **unknown
        optical train** -- see TestOpticalTrainKnown in
        test_camera_interface.py and the no-gate cases in
        test_optics_solving.py.
        """
        measured_debug_frame_fov = 10.2

        estimate, max_error = build_optical_train("hq").solver_fov_params()
        assert estimate - max_error < measured_debug_frame_fov < estimate + max_error

        estimate, max_error = build_optical_train("imx296").solver_fov_params()
        assert measured_debug_frame_fov < estimate - max_error
