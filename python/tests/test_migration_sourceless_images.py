"""Unit tests for the v2.7.0 sourceless-images rename migration (ADR 0018)."""

import importlib.util
import pathlib

import pytest

# The migration is stdlib-only and invoked by absolute path on-device (it must
# not import PiFinder), so load it directly from its file.
_MIGRATION_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "PiFinder"
    / "migrations"
    / "v2_7_0_sourceless_images.py"
)
_spec = importlib.util.spec_from_file_location(
    "v2_7_0_sourceless_images", _MIGRATION_PATH
)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


def _bucket(base, image_name):
    d = base / image_name[-1]
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.mark.unit
class TestMigration:
    def test_poss_wins_when_both_present(self, tmp_path):
        b = _bucket(tmp_path, "NGC224")
        (b / "NGC224_POSS.jpg").write_text("poss")
        (b / "NGC224_SDSS.jpg").write_text("sdss")

        renamed, removed = migration.migrate_images(str(tmp_path))

        assert (renamed, removed) == (1, 1)
        assert (b / "NGC224.jpg").read_text() == "poss"
        assert not (b / "NGC224_POSS.jpg").exists()
        assert not (b / "NGC224_SDSS.jpg").exists()

    def test_sdss_only_is_renamed(self, tmp_path):
        b = _bucket(tmp_path, "NGC3031")
        (b / "NGC3031_SDSS.jpg").write_text("sdss")

        migration.migrate_images(str(tmp_path))

        assert (b / "NGC3031.jpg").read_text() == "sdss"
        assert not (b / "NGC3031_SDSS.jpg").exists()

    def test_existing_sourceless_target_kept_legacy_removed(self, tmp_path):
        b = _bucket(tmp_path, "IC10")
        (b / "IC10.jpg").write_text("existing")
        (b / "IC10_POSS.jpg").write_text("legacy")

        renamed, removed = migration.migrate_images(str(tmp_path))

        assert (renamed, removed) == (0, 1)
        assert (b / "IC10.jpg").read_text() == "existing"
        assert not (b / "IC10_POSS.jpg").exists()

    def test_idempotent(self, tmp_path):
        b = _bucket(tmp_path, "NGC224")
        (b / "NGC224_POSS.jpg").write_text("poss")
        (b / "NGC224_SDSS.jpg").write_text("sdss")

        first = migration.migrate_images(str(tmp_path))
        second = migration.migrate_images(str(tmp_path))

        assert first == (1, 1)
        assert second == (0, 0)  # nothing left to do
        assert (b / "NGC224.jpg").read_text() == "poss"

    def test_missing_dir_is_noop(self, tmp_path):
        assert migration.migrate_images(str(tmp_path / "does_not_exist")) == (0, 0)
