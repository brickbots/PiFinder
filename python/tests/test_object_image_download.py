"""Unit tests for the app-owned object-image download controller (ADR 0018)."""

import threading
import time
import types

import pytest

from PiFinder import object_image_download as dl
from PiFinder import object_image_store as store


def _wait_idle(downloader, timeout=5.0):
    deadline = time.time() + timeout
    while downloader.is_active() and time.time() < deadline:
        time.sleep(0.01)
    assert not downloader.is_active(), "download did not finish in time"


@pytest.fixture(autouse=True)
def _no_real_io(monkeypatch):
    # Never touch the disk or network from the controller in these tests.
    monkeypatch.setattr(store, "create_catalog_image_dirs", lambda: None)
    monkeypatch.setattr(
        store, "new_session", lambda: types.SimpleNamespace(close=lambda: None)
    )


@pytest.mark.unit
class TestController:
    def test_runs_to_completion(self, monkeypatch):
        monkeypatch.setattr(
            store,
            "download_object_image",
            lambda session, name, **kw: store.RESULT_DOWNLOADED,
        )
        downloader = dl.ObjectImageDownloader(workers=2)
        assert downloader.start(["A", "B", "C"])
        _wait_idle(downloader)

        progress = downloader.progress()
        assert progress.state == dl.DONE
        assert progress.total == 3
        assert progress.downloaded == 3
        assert progress.completed == 3
        assert progress.percent == 100
        assert not progress.active

    def test_tallies_mixed_results(self, monkeypatch):
        outcomes = {
            "A": store.RESULT_DOWNLOADED,
            "B": store.RESULT_SKIPPED,
            "C": store.RESULT_MISSING,
            "D": store.RESULT_ERROR,
        }
        monkeypatch.setattr(
            store,
            "download_object_image",
            lambda session, name, **kw: outcomes[name],
        )
        downloader = dl.ObjectImageDownloader(workers=4)
        downloader.start(list(outcomes))
        _wait_idle(downloader)

        progress = downloader.progress()
        assert (
            progress.downloaded,
            progress.skipped,
            progress.missing,
            progress.errors,
        ) == (1, 1, 1, 1)
        assert progress.state == dl.DONE

    def test_second_start_while_active_is_rejected(self, monkeypatch):
        release = threading.Event()
        monkeypatch.setattr(
            store,
            "download_object_image",
            lambda session, name, **kw: (release.wait(2), store.RESULT_DOWNLOADED)[1],
        )
        downloader = dl.ObjectImageDownloader(workers=1)
        assert downloader.start(["A"])
        assert downloader.start(["B"]) is False  # already running
        release.set()
        _wait_idle(downloader)

    def test_cancel_marks_cancelled_and_keeps_progress(self, monkeypatch):
        release = threading.Event()

        def slow(session, name, **kw):
            release.wait(2)
            return store.RESULT_DOWNLOADED

        monkeypatch.setattr(store, "download_object_image", slow)
        downloader = dl.ObjectImageDownloader(workers=1)
        downloader.start(["A", "B", "C", "D"])
        downloader.cancel()
        release.set()
        _wait_idle(downloader)
        assert downloader.progress().state == dl.CANCELLED


@pytest.mark.unit
class TestProgressSnapshot:
    def test_percent_and_completed(self):
        p = dl.DownloadProgress(
            state=dl.RUNNING,
            total=200,
            downloaded=10,
            skipped=5,
            missing=4,
            errors=1,
        )
        assert p.completed == 20
        assert p.percent == 10
        assert p.active

    def test_zero_total_percent(self):
        p = dl.DownloadProgress(dl.IDLE, 0, 0, 0, 0, 0)
        assert p.percent == 0
