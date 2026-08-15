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
    LENSES,
    SOLVER_IMAGE_PIXELS,
    Lens,
    OpticalTrain,
    OpticalTrainResolver,
    build_optical_train,
    get_lens,
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

    def test_unmeasured_lengths_are_flagged_as_such(self):
        # The 12mm's effective length is its nominal standing in for a
        # measurement nobody has taken. That has to stay visible in the data,
        # not just in a comment, or it gets quietly treated as calibrated.
        assert LENSES["12mm"].effective_focal_length_measured is False
        assert LENSES["16mm"].effective_focal_length_measured is True

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
        a [8.0, 16.0] window. A 12mm lens on an imx296 images ~17.8 degrees
        and could not solve at all.
        """
        fov = build_optical_train("imx296", "12mm").fov_degrees
        assert fov == pytest.approx(17.78, abs=0.05)
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
        is the entire reason the debug camera's declared sensor changed.
        """
        measured_debug_frame_fov = 10.2

        estimate, max_error = build_optical_train("hq").solver_fov_params()
        assert estimate - max_error < measured_debug_frame_fov < estimate + max_error

        estimate, max_error = build_optical_train("imx296").solver_fov_params()
        assert measured_debug_frame_fov < estimate - max_error
