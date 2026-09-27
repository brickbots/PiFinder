"""Tests for lens self-heal: promoting an assumed lens to a stated one.

The device cannot detect its lens, but it can *measure* one -- a successful
solve reports the field of view it fitted, and dividing the known sensor out of
that names the lens. This is the safety envelope around acting on that
measurement, which matters because the write is one-way: once a lens is stated
the FOV gate tightens around it, so a wrong write leaves a device that can no
longer measure its way out.

See docs/adr/0029-fov-gate-width-follows-lens-confidence.md.
"""

import pytest

from PiFinder.integrator import LENS_IDENTIFY_CONSECUTIVE, LensSelfHeal
from PiFinder.optics import build_optical_train
from PiFinder.types.positioning import Pointing, SolveDiagnostics, SuccessfulSolve


class FakeConfig:
    """Just enough Config to see what self-heal does, and in what order.

    ``load_config`` is recorded because the ordering is load-bearing: the
    integrator's dict was loaded at process start and ``dump_config`` rewrites
    the whole file from it, so writing without reloading first would revert
    every setting changed from the menu since boot.
    """

    def __init__(self, options=None):
        self.options = dict(options or {})
        self.calls = []

    def load_config(self):
        self.calls.append("load_config")

    def set_option(self, option, value):
        self.calls.append(("set_option", option, value))
        self.options[option] = value

    def get_option(self, option, default=None):
        return self.options.get(option, default)


class FakeSharedState:
    def __init__(self, camera_type="imx462", camera_lens=None, train_known=True):
        self._camera_type = camera_type
        self._camera_lens = camera_lens
        self._train_known = train_known
        self.published = []

    def camera_type(self):
        return self._camera_type

    def camera_lens(self):
        return self._camera_lens

    def optical_train_known(self):
        return self._train_known

    def set_optical_train_known(self, value):
        self._train_known = value

    def set_camera_lens(self, value):
        self._camera_lens = value
        self.published.append(value)


def _solve(fov):
    """A SuccessfulSolve carrying nothing but the fitted FOV that matters."""
    pointing = Pointing(RA=0.0, Dec=0.0, Roll=0.0)
    return SuccessfulSolve(
        camera=pointing,
        aligned=pointing,
        imu_anchor=None,
        last_solve_attempt=0.0,
        last_solve_success=0.0,
        diagnostics=SolveDiagnostics(Matches=20, FOV=fov),
    )


# What an imx462 with the 12mm actually images -- the rev4 units that stopped
# solving on 2.6.2 while assuming the 16mm.
TWELVE_MM_ON_IMX462 = build_optical_train("imx462", "12mm").fov_degrees
SIXTEEN_MM_ON_IMX462 = build_optical_train("imx462", "16mm").fov_degrees

# What tetra3 fits the archived frames in test_images/ at -- the frames the
# debug camera replays. Measured, not derived; test_optics_solving.py asserts
# the same figure against the real solver.
DEBUG_FRAME_FITTED_FOV = 10.20


def _feed(healer, fov, times):
    for _ in range(times):
        healer.observe(_solve(fov))


@pytest.mark.unit
class TestSelfHealWrites:
    """The path that fixes the affected units."""

    def test_writes_after_three_agreeing_solves(self):
        cfg, state = FakeConfig(), FakeSharedState()
        healer = LensSelfHeal(cfg, state)

        _feed(healer, TWELVE_MM_ON_IMX462, LENS_IDENTIFY_CONSECUTIVE)

        assert cfg.options["camera_lens"] == "12mm"
        assert state.camera_lens() == "12mm"

    def test_does_not_write_before_the_third(self):
        # A single rogue fit must not be able to state a lens.
        cfg, state = FakeConfig(), FakeSharedState()
        healer = LensSelfHeal(cfg, state)

        _feed(healer, TWELVE_MM_ON_IMX462, LENS_IDENTIFY_CONSECUTIVE - 1)

        assert "camera_lens" not in cfg.options
        assert state.camera_lens() is None

    def test_the_run_must_be_consecutive(self):
        # Two 12mm fits, an unidentifiable one, then a third 12mm is not
        # three in a row -- the interruption resets the count.
        cfg, state = FakeConfig(), FakeSharedState()
        healer = LensSelfHeal(cfg, state)

        _feed(healer, TWELVE_MM_ON_IMX462, 2)
        _feed(healer, 20.0, 1)
        _feed(healer, TWELVE_MM_ON_IMX462, 1)

        assert "camera_lens" not in cfg.options

    def test_disagreeing_identifications_do_not_accumulate(self):
        cfg, state = FakeConfig(), FakeSharedState()
        healer = LensSelfHeal(cfg, state)

        for _ in range(LENS_IDENTIFY_CONSECUTIVE):
            healer.observe(_solve(TWELVE_MM_ON_IMX462))
            healer.observe(_solve(SIXTEEN_MM_ON_IMX462))

        # Every solve alternates, so no lens ever reaches a run of three.
        assert "camera_lens" not in cfg.options

    def test_reloads_config_before_writing(self):
        """Ordering, not just the fact of a reload.

        dump_config rewrites the whole file from the dict this process loaded
        at start-up, so a reload after the set_option would either be pointless
        or clobber the value just written.
        """
        cfg, state = FakeConfig(), FakeSharedState()
        healer = LensSelfHeal(cfg, state)

        _feed(healer, TWELVE_MM_ON_IMX462, LENS_IDENTIFY_CONSECUTIVE)

        assert cfg.calls == ["load_config", ("set_option", "camera_lens", "12mm")]

    def test_publishes_to_shared_state_so_the_solver_sees_it(self):
        # The config write alone would not take effect until a restart; the
        # solver re-reads the lens from shared state per frame.
        cfg, state = FakeConfig(), FakeSharedState()
        healer = LensSelfHeal(cfg, state)

        _feed(healer, TWELVE_MM_ON_IMX462, LENS_IDENTIFY_CONSECUTIVE)

        assert state.published == ["12mm"]

    def test_the_gate_narrows_onto_the_healed_lens(self):
        """The point of the whole exercise, asserted end to end.

        Before: a wide assumed gate that admits the frame. After: a narrow
        stated gate centred on the lens the device measured for itself.
        """
        cfg, state = FakeConfig(), FakeSharedState()
        healer = LensSelfHeal(cfg, state)

        before = build_optical_train("imx462", None)
        _feed(healer, TWELVE_MM_ON_IMX462, LENS_IDENTIFY_CONSECUTIVE)
        after = build_optical_train("imx462", state.camera_lens())

        assert not before.lens_stated and after.lens_stated
        assert after.solver_fov_params()[1] < before.solver_fov_params()[1]
        assert after.fov_degrees == pytest.approx(TWELVE_MM_ON_IMX462)

    def test_writes_only_once(self):
        # The write ends the condition it triggers on, so a device self-heals
        # at most once in its life. Nothing should rewrite it every frame.
        cfg, state = FakeConfig(), FakeSharedState()
        healer = LensSelfHeal(cfg, state)

        _feed(healer, TWELVE_MM_ON_IMX462, LENS_IDENTIFY_CONSECUTIVE * 4)

        assert state.published == ["12mm"]
        assert cfg.calls.count("load_config") == 1


@pytest.mark.unit
class TestSelfHealHoldsOff:
    """Every case where writing nothing is the right answer."""

    def test_never_overwrites_a_stated_lens(self):
        """The user's claim stays authoritative.

        Even when the measurement disagrees -- that is a mis-stated lens,
        which ADR 0027 deliberately does not recover from, and quietly
        overruling the setting would make the Lens menu a lie.
        """
        cfg = FakeConfig({"camera_lens": "16mm"})
        state = FakeSharedState(camera_lens="16mm")
        healer = LensSelfHeal(cfg, state)

        _feed(healer, TWELVE_MM_ON_IMX462, LENS_IDENTIFY_CONSECUTIVE * 2)

        assert cfg.options["camera_lens"] == "16mm"
        assert state.published == []
        assert cfg.calls == []

    def test_writes_nothing_for_a_lens_we_do_not_sell(self):
        # Third-party glass keeps the wide gate and approximate SQM forever,
        # which is honest: we do not know its focal length.
        cfg, state = FakeConfig(), FakeSharedState()
        healer = LensSelfHeal(cfg, state)

        _feed(healer, 20.0, LENS_IDENTIFY_CONSECUTIVE * 2)

        assert "camera_lens" not in cfg.options
        assert state.published == []

    def test_writes_nothing_without_a_fitted_fov(self):
        # SolveDiagnostics.FOV is Optional; an absent measurement is not a
        # measurement of zero.
        cfg, state = FakeConfig(), FakeSharedState()
        healer = LensSelfHeal(cfg, state)

        for _ in range(LENS_IDENTIFY_CONSECUTIVE * 2):
            healer.observe(_solve(None))

        assert "camera_lens" not in cfg.options

    def test_a_menu_change_mid_run_stops_an_in_flight_promotion(self):
        # Two agreeing solves, then the user states a lens. The pending run
        # must not carry through and overwrite what they just chose.
        cfg, state = FakeConfig(), FakeSharedState()
        healer = LensSelfHeal(cfg, state)

        _feed(healer, TWELVE_MM_ON_IMX462, LENS_IDENTIFY_CONSECUTIVE - 1)
        state.set_camera_lens("16mm")
        state.published.clear()
        _feed(healer, TWELVE_MM_ON_IMX462, LENS_IDENTIFY_CONSECUTIVE)

        assert state.camera_lens() == "16mm"
        assert state.published == []

    def test_an_unidentifiable_fit_logs_once_not_once_per_frame(self, caplog):
        cfg, state = FakeConfig(), FakeSharedState()
        healer = LensSelfHeal(cfg, state)

        with caplog.at_level("INFO", logger="IMU.Integrator"):
            _feed(healer, 20.0, 25)

        assert len(caplog.records) == 1
        assert "matches no lens" in caplog.records[0].getMessage()

    def test_an_unknown_optical_train_never_promotes(self):
        """The exact `--camera debug` case, which used to write.

        The archived frames fit 10.20 deg, which is 1.3% off the hq's derived
        10.33 -- comfortably inside LENS_IDENTIFY_TOLERANCE, so this is not a
        measurement self-heal would reject on its merits. It has to be
        declined on provenance: the fit measures the train the frames were
        *recorded* on, and the developer's config is about a different
        machine. Writing 25mm here is what leaves a real imx462 attached
        afterwards deriving 6.4 deg and unable to heal its way back.
        """
        cfg = FakeConfig()
        state = FakeSharedState(camera_type="hq", train_known=False)
        healer = LensSelfHeal(cfg, state)

        _feed(healer, DEBUG_FRAME_FITTED_FOV, LENS_IDENTIFY_CONSECUTIVE * 4)

        assert "camera_lens" not in cfg.options
        assert state.published == []
        assert cfg.calls == []

    def test_the_same_fit_would_have_been_promoted_on_real_optics(self):
        # Pins the test above to provenance rather than to the number: change
        # only train_known and the identical measurement writes.
        cfg = FakeConfig()
        state = FakeSharedState(camera_type="hq", train_known=True)
        healer = LensSelfHeal(cfg, state)

        _feed(healer, DEBUG_FRAME_FITTED_FOV, LENS_IDENTIFY_CONSECUTIVE)

        assert cfg.options["camera_lens"] == "25mm"

    def test_an_unknown_train_logs_once_not_once_per_frame(self, caplog):
        cfg = FakeConfig()
        state = FakeSharedState(camera_type="hq", train_known=False)
        healer = LensSelfHeal(cfg, state)

        with caplog.at_level("INFO", logger="IMU.Integrator"):
            _feed(healer, DEBUG_FRAME_FITTED_FOV, 25)

        assert len(caplog.records) == 1
        assert "Optical train is unknown" in caplog.records[0].getMessage()

    def test_a_run_does_not_survive_the_train_going_unknown(self):
        """Agreement counted on real optics must not be spent on a recording.

        Ordering matters here: the check sits ahead of the stated-lens branch
        precisely so it resets the streak rather than falling through it.
        """
        cfg, state = FakeConfig(), FakeSharedState(camera_type="hq")
        healer = LensSelfHeal(cfg, state)

        _feed(healer, DEBUG_FRAME_FITTED_FOV, LENS_IDENTIFY_CONSECUTIVE - 1)
        state.set_optical_train_known(False)
        _feed(healer, DEBUG_FRAME_FITTED_FOV, 1)
        state.set_optical_train_known(True)
        _feed(healer, DEBUG_FRAME_FITTED_FOV, 1)

        assert "camera_lens" not in cfg.options


@pytest.mark.unit
class TestSelfHealIsNeverFatal:
    """A failed promotion must cost the promotion, not the pointing."""

    def test_a_config_write_failure_is_contained(self):
        class ReadOnlyConfig(FakeConfig):
            def set_option(self, option, value):
                raise OSError("Read-only file system")

        cfg, state = ReadOnlyConfig(), FakeSharedState()
        healer = LensSelfHeal(cfg, state)

        _feed(healer, TWELVE_MM_ON_IMX462, LENS_IDENTIFY_CONSECUTIVE)

        assert state.camera_lens() is None

    def test_a_lost_manager_connection_is_contained(self):
        class BrokenState(FakeSharedState):
            def camera_lens(self):
                raise BrokenPipeError("manager gone")

        cfg, state = FakeConfig(), BrokenState()
        healer = LensSelfHeal(cfg, state)

        _feed(healer, TWELVE_MM_ON_IMX462, LENS_IDENTIFY_CONSECUTIVE)

        assert "camera_lens" not in cfg.options

    def test_it_gives_up_rather_than_retrying_every_frame(self, caplog):
        class ReadOnlyConfig(FakeConfig):
            def set_option(self, option, value):
                raise OSError("Read-only file system")

        cfg, state = ReadOnlyConfig(), FakeSharedState()
        healer = LensSelfHeal(cfg, state)

        with caplog.at_level("WARNING", logger="IMU.Integrator"):
            _feed(healer, TWELVE_MM_ON_IMX462, LENS_IDENTIFY_CONSECUTIVE * 5)

        assert len(caplog.records) == 1


@pytest.mark.unit
class TestSelfHealAcrossSensors:
    """Behaviour that has to hold for hardware other than the affected units."""

    def test_the_hq_promotes_its_only_lens(self):
        # Harmless and correct: it states what is actually fitted, and the
        # hq's gate is the same either way, so nothing about solving changes.
        cfg = FakeConfig()
        state = FakeSharedState(camera_type="hq")
        healer = LensSelfHeal(cfg, state)

        _feed(healer, 10.2, LENS_IDENTIFY_CONSECUTIVE)

        assert cfg.options["camera_lens"] == "25mm"
        assert build_optical_train("hq", "25mm").solver_fov_params() == (
            build_optical_train("hq", None).solver_fov_params()
        )

    def test_an_unrecognised_sensor_does_not_raise(self):
        # camera_type is a plain string from another process. The integrator
        # must not fall over on one it does not know.
        cfg = FakeConfig()
        state = FakeSharedState(camera_type="none")
        healer = LensSelfHeal(cfg, state)

        _feed(healer, build_optical_train("imx296", "12mm").fov_degrees, 5)

        # Resolves through the imx296 fallback, so it identifies normally.
        assert cfg.options["camera_lens"] == "12mm"

    def test_identifies_the_assumed_lens_too(self):
        # A unit that did ship with the 16mm still gets promoted, which is
        # what narrows its gate back to 0027's width.
        cfg, state = FakeConfig(), FakeSharedState()
        healer = LensSelfHeal(cfg, state)

        _feed(healer, SIXTEEN_MM_ON_IMX462, LENS_IDENTIFY_CONSECUTIVE)

        assert cfg.options["camera_lens"] == "16mm"
