"""Transactional runtime catalog download tests."""

from pathlib import Path

import pytest
import requests

from PiFinder import download_utils


class FakeResponse:
    def __init__(self, chunks, headers=None):
        self.chunks = chunks
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        return iter(self.chunks)


@pytest.mark.unit
def test_atomic_download_replaces_only_after_validation(tmp_path, monkeypatch):
    destination = tmp_path / "catalog.txt"
    destination.write_bytes(b"old catalog")
    monkeypatch.setattr(
        download_utils.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(
            [b"new ", b"catalog"], {"content-length": "11"}
        ),
    )
    observed_during_validation = []

    def validate(path: Path):
        observed_during_validation.append(destination.read_bytes())
        assert path.read_bytes() == b"new catalog"

    progress = []
    result = download_utils.download_atomic(
        "https://example.test/catalog",
        destination,
        progress_callback=progress.append,
        validator=validate,
    )
    assert result.success
    assert observed_during_validation == [b"old catalog"]
    assert destination.read_bytes() == b"new catalog"
    assert progress[0] == 0
    assert progress[-1] == 100


@pytest.mark.unit
def test_failed_validation_preserves_old_catalog(tmp_path, monkeypatch):
    destination = tmp_path / "catalog.txt"
    destination.write_bytes(b"known good")
    monkeypatch.setattr(
        download_utils.requests,
        "get",
        lambda *args, **kwargs: FakeResponse([b"broken"]),
    )

    def reject(_path):
        raise ValueError("bad catalog")

    result = download_utils.download_atomic(
        "https://example.test/catalog", destination, validator=reject
    )
    assert not result.success
    assert destination.read_bytes() == b"known good"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.unit
def test_unknown_content_length_reports_indeterminate_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(
        download_utils.requests,
        "get",
        lambda *args, **kwargs: FakeResponse([b"content"]),
    )
    progress = []
    result = download_utils.download_atomic(
        "https://example.test/catalog",
        tmp_path / "catalog.txt",
        progress_callback=progress.append,
    )
    assert result.success
    assert progress == [None, 100]


@pytest.mark.unit
def test_network_failure_preserves_old_catalog(tmp_path, monkeypatch):
    destination = tmp_path / "catalog.txt"
    destination.write_bytes(b"old")

    def fail(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(download_utils.requests, "get", fail)
    result = download_utils.download_atomic("https://example.test/catalog", destination)
    assert not result.success
    assert destination.read_bytes() == b"old"
