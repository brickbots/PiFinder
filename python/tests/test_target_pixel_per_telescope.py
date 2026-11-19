"""Each telescope keeps its own alignment point (target pixel).

The target pixel is the (Y, X) camera pixel at the centre of the eyepiece.
It depends on how the PiFinder sits on a particular telescope, so it is
stored on the ``Telescope`` record.  A telescope that has never been aligned
falls back to the global ``target_pixel`` -- the single point every
telescope shared before this change -- so an upgrade changes nothing until
the user aligns.  See docs/adr/0047-alignment-point-belongs-to-the-telescope.md.
"""

import json
import math
from types import SimpleNamespace

import pytest

# Installs the ``_()`` gettext builtin that PiFinder.ui modules rely on.
import PiFinder.i18n  # noqa: F401

from PiFinder import config
from PiFinder.equipment import Equipment, Telescope
from PiFinder.ui import callbacks


def a_telescope(name="Dobsonian", target_pixel=None):
    return Telescope(
        make="Generic",
        name=name,
        aperture_mm=200,
        focal_length_mm=1000,
        obstruction_perc=17.0,
        mount_type="alt/az",
        flip_image=False,
        flop_image=False,
        reverse_arrow_a=False,
        reverse_arrow_b=False,
        target_pixel=target_pixel,
    )


def telescope_dict(name, target_pixel=None, include_field=True):
    record = {
        "make": "Generic",
        "name": name,
        "aperture_mm": 200,
        "focal_length_mm": 1000,
        "obstruction_perc": 17.0,
        "mount_type": "alt/az",
        "flip_image": False,
        "flop_image": False,
        "reverse_arrow_a": False,
        "reverse_arrow_b": False,
    }
    if include_field:
        record["target_pixel"] = target_pixel
    return record


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config.utils, "data_dir", tmp_path)
    return tmp_path


def write_config(config_dir, **options):
    (config_dir / "config.json").write_text(json.dumps(options))


def read_config(config_dir):
    return json.loads((config_dir / "config.json").read_text())


# ── the record ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestTelescopeRecord:
    def test_unaligned_by_default(self):
        assert a_telescope().target_pixel is None

    def test_equality_ignores_the_alignment_point(self):
        """Records are found by value; aligning must not hide one."""
        assert a_telescope(target_pixel=[1.0, 2.0]) == a_telescope()

    def test_selecting_a_stale_copy_still_finds_the_aligned_telescope(self):
        """The device menu holds the records it was built from. After a
        reload_config, cfg.equipment holds new ones, and one of them may
        have been aligned since."""
        menu_value = a_telescope("B")
        equipment = Equipment(
            telescopes=[a_telescope("A"), a_telescope("B", [300.0, 200.0])],
            eyepieces=[],
        )

        equipment.set_active_telescope(menu_value)

        assert equipment.active_telescope_index == 1

    def test_round_trips_through_config(self):
        equipment = Equipment(
            telescopes=[a_telescope(target_pixel=[300.5, 200.0])], eyepieces=[]
        )

        loaded = Equipment.from_dict(json.loads(json.dumps(equipment.to_dict())))

        assert loaded.telescopes[0].target_pixel == [300.5, 200.0]

    def test_a_record_written_before_the_field_existed_loads_unaligned(self):
        loaded = Equipment.from_dict(
            {
                "telescopes": [telescope_dict("Old", include_field=False)],
                "eyepieces": [],
            }
        )

        assert loaded.telescopes[0].target_pixel is None


# ── which point applies ────────────────────────────────────────────


@pytest.mark.unit
class TestActiveTargetPixel:
    def test_a_new_unit_uses_the_image_centre(self, config_dir):
        """No config.json: the shipped default telescope is active and has
        no point of its own, so it falls back to the shipped global one."""
        cfg = config.Config()

        assert cfg.equipment.active_telescope is not None
        assert cfg.equipment.active_telescope.target_pixel is None
        assert cfg.active_target_pixel() == (256.0, 256.0)

    def test_an_unaligned_telescope_uses_the_global_point(self, config_dir):
        """An upgraded unit keeps today's alignment until it re-aligns."""
        write_config(
            config_dir,
            target_pixel=[310.0, 190.0],
            equipment={
                "telescopes": [telescope_dict("A")],
                "eyepieces": [],
                "active_telescope_index": 0,
            },
        )

        assert config.Config().active_target_pixel() == (310.0, 190.0)

    def test_an_aligned_telescope_uses_its_own_point(self, config_dir):
        write_config(
            config_dir,
            target_pixel=[310.0, 190.0],
            equipment={
                "telescopes": [telescope_dict("A", [100.0, 400.0])],
                "eyepieces": [],
                "active_telescope_index": 0,
            },
        )

        assert config.Config().active_target_pixel() == (100.0, 400.0)

    def test_switching_telescope_switches_the_point(self, config_dir):
        write_config(
            config_dir,
            target_pixel=[310.0, 190.0],
            equipment={
                "telescopes": [
                    telescope_dict("A", [100.0, 400.0]),
                    telescope_dict("B"),
                ],
                "eyepieces": [],
                "active_telescope_index": 0,
            },
        )
        cfg = config.Config()

        cfg.set_option("equipment.active_telescope", cfg.equipment.telescopes[1])

        assert cfg.active_target_pixel() == (310.0, 190.0)

    def test_no_active_telescope_uses_the_global_point(self, config_dir):
        """Only reachable with an empty telescope list (load_config puts the
        defaults back otherwise, and index -1 selects the last telescope),
        but the resolver must still answer."""
        write_config(config_dir, target_pixel=[310.0, 190.0])
        cfg = config.Config()
        cfg.equipment = Equipment(telescopes=[], eyepieces=[])

        assert cfg.active_target_pixel() == (310.0, 190.0)

    def test_an_unusable_global_point_falls_back_to_the_centre(self, config_dir):
        write_config(
            config_dir,
            target_pixel="centre",
            equipment={
                "telescopes": [telescope_dict("A")],
                "eyepieces": [],
                "active_telescope_index": 0,
            },
        )

        assert config.Config().active_target_pixel() == (256.0, 256.0)

    @pytest.mark.parametrize("bad", ["garbage", 5, [1.0], [1.0, "x"], {"y": 1}])
    def test_an_unusable_point_does_not_cost_the_equipment(
        self, config_dir, caplog, bad
    ):
        """A hand-edited point is dropped, not allowed to make from_dict
        raise and replace every telescope with the shipped defaults."""
        write_config(
            config_dir,
            target_pixel=[310.0, 190.0],
            equipment={
                "telescopes": [telescope_dict("Mine", bad)],
                "eyepieces": [],
                "active_telescope_index": 0,
            },
        )

        cfg = config.Config()

        assert cfg.equipment.telescopes[0].name == "Mine"
        assert cfg.equipment.telescopes[0].target_pixel is None
        assert cfg.active_target_pixel() == (310.0, 190.0)
        assert "Ignoring unusable alignment point" in caplog.text

    def test_a_non_finite_point_is_unusable(self, config_dir):
        write_config(
            config_dir,
            target_pixel=[310.0, 190.0],
            equipment={
                "telescopes": [telescope_dict("A", [math.nan, 1.0])],
                "eyepieces": [],
                "active_telescope_index": 0,
            },
        )

        assert config.Config().active_target_pixel() == (310.0, 190.0)


# ── saving a point ─────────────────────────────────────────────────


@pytest.mark.unit
class TestSaveTargetPixel:
    def test_saves_to_the_active_telescope_only(self, config_dir):
        write_config(
            config_dir,
            target_pixel=[310.0, 190.0],
            equipment={
                "telescopes": [telescope_dict("A"), telescope_dict("B")],
                "eyepieces": [],
                "active_telescope_index": 0,
            },
        )
        cfg = config.Config()

        cfg.save_target_pixel((120, 330))

        saved = read_config(config_dir)
        assert saved["equipment"]["telescopes"][0]["target_pixel"] == [120.0, 330.0]
        assert saved["equipment"]["telescopes"][1]["target_pixel"] is None
        assert saved["target_pixel"] == [310.0, 190.0]  # global untouched
        # and it survives a restart
        assert config.Config().active_target_pixel() == (120.0, 330.0)

    def test_saves_to_the_global_point_with_no_telescope(self, config_dir):
        cfg = config.Config()
        cfg.equipment = Equipment(telescopes=[], eyepieces=[])

        cfg.save_target_pixel((120.0, 330.0))

        assert read_config(config_dir)["target_pixel"] == [120.0, 330.0]
        assert cfg.active_target_pixel() == (120.0, 330.0)

    def test_rejects_something_that_is_not_a_pixel(self, config_dir):
        with pytest.raises(ValueError):
            config.Config().save_target_pixel(None)


# ── selecting a telescope on the device ────────────────────────────


@pytest.mark.unit
def test_selecting_a_telescope_hands_the_solver_its_point():
    """The Telescope menu's post_callback pushes the point to shared state,
    which the solver reads on every solve."""
    pushed = []
    ui_module = SimpleNamespace(
        shared_state=SimpleNamespace(set_target_pixel=pushed.append),
        config_object=SimpleNamespace(active_target_pixel=lambda: (100.0, 400.0)),
    )

    callbacks.apply_target_pixel(ui_module)

    assert pushed == [(100.0, 400.0)]
