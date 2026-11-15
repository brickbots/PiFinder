"""Satellite downloads that fail: the catalog, the retries and the status.

The tests use temporary data directories and mock downloads. They use no
network.
"""

import datetime
import json
import multiprocessing
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
import requests

# Installs the ``_()`` gettext builtin that PiFinder.ui modules rely on.
import PiFinder.i18n  # noqa: F401

import PiFinder.download_utils as download_utils
import PiFinder.satellite_catalog as satellite_catalog
import PiFinder.satellites as satellites
import PiFinder.web_satellites as web_satellites
from PiFinder import utils
from PiFinder.catalog_base import CatalogState, CatalogStatus
from PiFinder.state import Location
from PiFinder.ui import sat_groups
from PiFinder.ui.base import UIModule
from PiFinder.ui.object_list import UIObjectList

DATA = Path(__file__).parent / "data" / "satellites"
PYTHON_DIR = Path(__file__).resolve().parent.parent
NO_GP_DATA = "No GP data found"
# The longest device text line: about 16 characters fit the 128 px screen.
DEVICE_LINE_CHARS = 16


def system_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def iss_epoch() -> datetime.datetime:
    results, _errors = satellites.parse_elements((DATA / "25544.3le").read_text())
    return results[0].epoch


class SharedState:
    def __init__(self, dt):
        self.dt = dt

    def altaz_ready(self):
        return True

    def datetime(self):
        return self.dt

    def location(self):
        return Location(
            lat=50.85, lon=4.35, altitude=50.0, lock=True, timezone="Europe/Brussels"
        )


def http_response(status: int, text: str) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = text.encode()
    response.url = "https://celestrak.org/test"
    return response


def failed_like_404(group, directory=None, progress_callback=None):
    """CelesTrak without data for the group: HTTP 404, "No GP data found"."""
    return download_utils.DownloadResult(
        False,
        None,
        None,
        "404 Client Error",
        download_utils.ERROR_HTTP,
        404,
        NO_GP_DATA,
    )


def failed_like_no_network(group, directory=None, progress_callback=None):
    """A network fault: the request does not reach CelesTrak."""
    return download_utils.DownloadResult(
        False, None, None, "no route", download_utils.ERROR_NETWORK
    )


def write_groups(directory: Path, selected: list[str], with_files: list[str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for group in with_files:
        source = "visual.tle" if group == "visual" else "25544.3le"
        satellites.group_file(group, directory).write_text((DATA / source).read_text())
    (directory / satellites.SELECTION_FILE_NAME).write_text(
        json.dumps({"groups": selected})
    )


def built_catalog(directory: Path) -> satellite_catalog.SatelliteCatalog:
    """A catalog after its first use: the boot download ran, then the
    update thread built the objects."""
    cat = satellite_catalog.SatelliteCatalog(
        SharedState(iss_epoch() + datetime.timedelta(days=1)),
        data_directory=directory,
        start_threads=False,
    )
    cat._spawn_pass_worker = lambda: None
    cat._download_missing()
    cat.touch()
    cat._update_step()
    return cat


# ---------------------------------------------------------------------------
# The empty catalog
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_failed_group_does_not_block_the_groups_with_files(tmp_path, monkeypatch):
    monkeypatch.setattr(satellites, "download_group", failed_like_404)
    write_groups(
        tmp_path,
        ["amateur", "last-30-days", "stations", "visual"],
        ["amateur", "stations", "visual"],
    )
    cat = built_catalog(tmp_path)
    assert cat.get_count() > 0
    status = cat.get_status()
    assert status.current == CatalogState.READY
    assert status.data == {"total": cat.get_count()}


@pytest.mark.unit
def test_catalog_of_failed_groups_only_says_download_failed(tmp_path, monkeypatch):
    # The bench: only the failed group is selected. The catalog has no
    # objects. It must not report READY, which shows "No objects match filter".
    monkeypatch.setattr(satellites, "download_group", failed_like_404)
    write_groups(tmp_path, ["last-30-days"], ["amateur", "stations", "visual"])
    cat = built_catalog(tmp_path)
    assert cat.get_count() == 0
    status = cat.get_status()
    assert status.current == CatalogState.ERROR
    assert status.data == {"reason": "failed", "groups": ["last-30-days"]}


@pytest.mark.unit
def test_catalog_without_any_file_says_download_failed(tmp_path, monkeypatch):
    # No selection file, no group file, and the default groups fail.
    monkeypatch.setattr(satellites, "download_group", failed_like_404)
    tmp_path.mkdir(exist_ok=True)
    cat = built_catalog(tmp_path)
    status = cat.get_status()
    assert status.current == CatalogState.ERROR
    assert status.data["reason"] == "failed"


@pytest.mark.unit
@pytest.mark.parametrize(
    "selected, files, status_entry, reason",
    [
        ([], [], None, "no_groups"),
        (["amateur"], [], None, "no_data"),
        (["amateur"], [], satellites.RESULT_DOWNLOADING, "downloading"),
        (["amateur"], [], satellites.RESULT_FAILED, "failed"),
    ],
)
def test_empty_catalog_reason(tmp_path, selected, files, status_entry, reason):
    write_groups(tmp_path, selected, files)
    if status_entry is not None:
        now = system_now().timestamp()
        (tmp_path / satellites.DOWNLOAD_STATUS_FILE_NAME).write_text(
            json.dumps(
                {"groups": {"amateur": {"result": status_entry, "last_attempt": now}}}
            )
        )
    assert satellites.catalog_empty_reason(tmp_path)["reason"] == reason


@pytest.mark.unit
def test_old_downloading_state_counts_as_failed(tmp_path):
    entry = satellites.GroupStatus(
        satellites.RESULT_DOWNLOADING,
        last_attempt=system_now().timestamp() - satellites.DOWNLOAD_STALE_SECONDS - 1,
    )
    assert entry.current_result(system_now()) == satellites.RESULT_FAILED


# ---------------------------------------------------------------------------
# Retries
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_retry_waits_grow_then_follow_the_age_rule():
    waits = [satellites.retry_wait_seconds(failures) for failures in range(1, 6)]
    twelve_hours = satellites.DOWNLOAD_INTERVAL_HOURS * 3600.0
    assert waits == [5 * 60.0, 15 * 60.0, 60 * 60.0, twelve_hours, twelve_hours]


@pytest.mark.unit
def test_retry_waits_after_an_http_answer_are_two_hours_or_more():
    waits = [
        satellites.retry_wait_seconds(failures, server_answered=True)
        for failures in range(1, 6)
    ]
    two_hours = 2 * 3600.0
    twelve_hours = satellites.DOWNLOAD_INTERVAL_HOURS * 3600.0
    assert satellites.MIN_FORCED_DOWNLOAD_SECONDS == two_hours
    assert waits == [two_hours, two_hours, two_hours, twelve_hours, twelve_hours]
    assert satellites.retry_wait_seconds(0, server_answered=True) == twelve_hours


@pytest.mark.unit
@pytest.mark.parametrize(
    "failed_download, expected",
    [
        # CelesTrak answered: each wait is at least 2 h.
        (failed_like_404, [2 * 3600.0, 2 * 3600.0, 2 * 3600.0, 12 * 3600.0]),
        # The request did not reach CelesTrak: the short waits.
        (failed_like_no_network, [5 * 60.0, 15 * 60.0, 60 * 60.0, 12 * 3600.0]),
    ],
)
def test_failed_group_waits_for_its_retry_time(
    tmp_path, monkeypatch, failed_download, expected
):
    calls = []

    def download(group, directory=None, progress_callback=None):
        calls.append(group)
        return failed_download(group)

    monkeypatch.setattr(satellites, "download_group", download)
    write_groups(tmp_path, ["last-30-days"], [])
    start = system_now()
    now = start
    for number, wait in enumerate(expected, start=1):
        result = satellites.refresh_groups(now, False, tmp_path)
        assert result.status == "failed" and len(calls) == number
        entry = satellites.load_download_status(tmp_path)["last-30-days"]
        assert entry.failures == number
        assert entry.next_retry == pytest.approx(now.timestamp() + wait)
        # Before the retry time no automatic download runs.
        early = now + datetime.timedelta(seconds=wait - 1)
        assert satellites.refresh_groups(early, False, tmp_path).status == "current"
        assert len(calls) == number
        now = now + datetime.timedelta(seconds=wait + 1)


@pytest.mark.unit
def test_user_update_tries_a_failed_group_at_once(tmp_path, monkeypatch):
    calls = []

    def download(group, directory=None, progress_callback=None):
        calls.append(group)
        if len(calls) == 1:
            # A network fault: no request reached CelesTrak.
            return failed_like_no_network(group)
        satellites.group_file(group, directory).write_text(
            (DATA / "25544.3le").read_text()
        )
        return download_utils.DownloadResult(True, None, None)

    monkeypatch.setattr(satellites, "download_group", download)
    write_groups(tmp_path, ["last-30-days"], [])
    now = system_now()
    assert satellites.refresh_groups(now, False, tmp_path).status == "failed"
    assert satellites.refresh_groups(now, False, tmp_path).status == "current"
    # A forced download ignores the retry time.
    result = satellites.refresh_groups(now, True, tmp_path)
    assert result.downloaded == ("last-30-days",)
    entry = satellites.load_download_status(tmp_path)["last-30-days"]
    assert entry.result == satellites.RESULT_OK and entry.failures == 0
    assert entry.sets == 1 and entry.error == ""
    assert entry.last_request == now.timestamp()
    # The 2 h rule of a forced download stays.
    later = system_now() + datetime.timedelta(seconds=1)
    assert satellites.refresh_groups(later, True, tmp_path).status == "too_soon"
    assert len(calls) == 2


@pytest.mark.unit
@pytest.mark.parametrize(
    "failed_download, answered",
    [
        (failed_like_404, True),
        (failed_like_no_network, False),
        (
            lambda group, directory=None, progress_callback=None: (
                download_utils.DownloadResult(
                    False, None, None, "timeout", download_utils.ERROR_TIMEOUT
                )
            ),
            False,
        ),
        (
            lambda group, directory=None, progress_callback=None: (
                download_utils.DownloadResult(
                    False, None, None, "bad", download_utils.ERROR_DATA
                )
            ),
            True,
        ),
    ],
)
def test_last_request_is_set_when_celestrak_answered(
    tmp_path, failed_download, answered
):
    now = system_now()
    satellites.record_download_start("last-30-days", now, tmp_path)
    satellites.record_download_end(
        "last-30-days", now, failed_download("last-30-days"), tmp_path
    )
    entry = satellites.load_download_status(tmp_path)["last-30-days"]
    assert entry.result == satellites.RESULT_FAILED
    assert entry.last_request == (now.timestamp() if answered else None)


@pytest.mark.unit
def test_network_fault_keeps_the_last_request_of_an_http_error(tmp_path):
    group = "last-30-days"
    first = system_now()
    satellites.record_download_end(group, first, failed_like_404(group), tmp_path)
    later = first + datetime.timedelta(minutes=10)
    satellites.record_download_end(
        group, later, failed_like_no_network(group), tmp_path
    )
    entry = satellites.load_download_status(tmp_path)[group]
    assert entry.failures == 2
    assert entry.last_request == first.timestamp()


@pytest.mark.unit
def test_forced_download_without_a_file_waits_2_h_after_an_http_error(
    tmp_path, monkeypatch
):
    calls = []

    def download(group, directory=None, progress_callback=None):
        calls.append(group)
        return failed_like_404(group)

    monkeypatch.setattr(satellites, "download_group", download)
    write_groups(tmp_path, ["last-30-days"], [])
    start = system_now()
    assert satellites.refresh_groups(start, True, tmp_path).status == "failed"
    assert not satellites.group_file("last-30-days", tmp_path).exists()

    two_hours = satellites.MIN_FORCED_DOWNLOAD_SECONDS
    for seconds in (1.0, 60.0, two_hours - 1):
        now = start + datetime.timedelta(seconds=seconds)
        waits = satellites.forced_download_wait(now, tmp_path)
        assert waits == {"last-30-days": pytest.approx(two_hours - seconds)}
        result = satellites.refresh_groups(now, True, tmp_path)
        assert result.status == "too_soon"
        assert result.wait_seconds == pytest.approx(two_hours - seconds)
    assert calls == ["last-30-days"]

    now = start + datetime.timedelta(seconds=two_hours + 1)
    assert satellites.forced_download_wait(now, tmp_path) == {"last-30-days": 0.0}
    assert satellites.refresh_groups(now, True, tmp_path).status == "failed"
    assert calls == ["last-30-days", "last-30-days"]


@pytest.mark.unit
def test_forced_download_without_a_file_is_not_refused_after_a_network_fault(
    tmp_path, monkeypatch
):
    calls = []

    def download(group, directory=None, progress_callback=None):
        calls.append(group)
        return failed_like_no_network(group)

    monkeypatch.setattr(satellites, "download_group", download)
    write_groups(tmp_path, ["last-30-days"], [])
    now = system_now()
    assert satellites.refresh_groups(now, True, tmp_path).status == "failed"
    assert satellites.forced_download_wait(now, tmp_path) == {"last-30-days": 0.0}
    assert satellites.refresh_groups(now, True, tmp_path).status == "failed"
    assert calls == ["last-30-days", "last-30-days"]


@pytest.mark.unit
def test_catalog_download_thread_wakes_at_the_retry_time(tmp_path, monkeypatch):
    # A network fault gives the first short retry wait, below the check
    # interval of the thread.
    monkeypatch.setattr(satellites, "download_group", failed_like_no_network)
    write_groups(tmp_path, ["last-30-days", "visual"], ["visual"])
    cat = satellite_catalog.SatelliteCatalog(
        SharedState(system_now()), data_directory=tmp_path, start_threads=False
    )
    cat.touch()
    wait = cat._download_step()
    assert wait == pytest.approx(satellites.FAILED_RETRY_SECONDS[0], abs=5)
    # An idle catalog does not retry.
    cat._last_use = cat._clock() - cat.IDLE_SECONDS - 1
    assert cat._download_step() is None


@pytest.mark.unit
def test_download_exception_is_a_failed_group(tmp_path, monkeypatch):
    def broken(group, directory=None, progress_callback=None):
        raise RuntimeError("broken")

    monkeypatch.setattr(satellites, "download_group", broken)
    write_groups(tmp_path, ["amateur", "visual"], [])
    result = satellites.refresh_groups(system_now(), True, tmp_path)
    assert result.failed == ("visual", "amateur")
    status = satellites.load_download_status(tmp_path)
    assert {status[group].result for group in result.failed} == {"failed"}


# ---------------------------------------------------------------------------
# The status file
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_status_file_is_written_on_start_and_end(tmp_path, monkeypatch):
    seen = []

    def download(group, directory=None, progress_callback=None):
        seen.append(satellites.load_download_status(tmp_path)[group].result)
        return failed_like_404(group)

    monkeypatch.setattr(satellites, "download_group", download)
    write_groups(tmp_path, ["last-30-days"], [])
    now = system_now()
    satellites.refresh_groups(now, True, tmp_path)
    assert seen == [satellites.RESULT_DOWNLOADING]
    data = json.loads((tmp_path / satellites.DOWNLOAD_STATUS_FILE_NAME).read_text())
    assert data == {
        "version": 1,
        "groups": {
            "last-30-days": {
                "result": "failed",
                "last_attempt": now.timestamp(),
                "last_success": None,
                "error": "CelesTrak has no data",
                "sets": 0,
                "failures": 1,
                "next_retry": now.timestamp() + 2 * 3600.0,
                "last_request": now.timestamp(),
            }
        },
    }


@pytest.mark.unit
def test_bad_status_file_reads_as_empty(tmp_path):
    (tmp_path / satellites.DOWNLOAD_STATUS_FILE_NAME).write_text("{not json")
    assert satellites.load_download_status(tmp_path) == {}


CHILD_WRITER = """
import sys
from datetime import datetime, timezone
from pathlib import Path
import PiFinder.satellites as satellites
from PiFinder.download_utils import DownloadResult

directory = Path(sys.argv[1])
for _number in range(int(sys.argv[2])):
    now = datetime.now(timezone.utc)
    satellites.record_download_start("amateur", now, directory)
    satellites.record_download_end(
        "amateur", now, DownloadResult(False, None, None, "x", "network"), directory
    )
"""


@pytest.mark.unit
def test_status_file_keeps_the_writes_of_two_processes(tmp_path):
    rounds = 30
    child = subprocess.Popen(
        [sys.executable, "-c", CHILD_WRITER, str(tmp_path), str(rounds)],
        cwd=PYTHON_DIR,
    )
    ok = download_utils.DownloadResult(True, None, None)
    satellites.group_file("visual", tmp_path).write_text(
        (DATA / "visual.tle").read_text()
    )
    for _number in range(rounds):
        now = system_now()
        satellites.record_download_start("visual", now, tmp_path)
        satellites.record_download_end("visual", now, ok, tmp_path)
    assert child.wait(timeout=60) == 0
    status = satellites.load_download_status(tmp_path)
    assert status["visual"].result == "ok" and status["visual"].sets > 1
    assert status["amateur"].result == "failed"
    assert status["amateur"].error == "No network"
    assert status["amateur"].failures == rounds


# ---------------------------------------------------------------------------
# Error texts
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "status, body, text",
    [
        (404, NO_GP_DATA, "CelesTrak has no data"),
        (404, "Not here", "HTTP error 404"),
        (503, "busy", "Server error 503"),
        (403, "", "Refused by CelesTrak (403)"),
    ],
)
def test_http_error_text(tmp_path, monkeypatch, status, body, text):
    monkeypatch.setattr(
        download_utils.requests, "get", lambda *a, **k: http_response(status, body)
    )
    result = satellites.download_group("last-30-days", tmp_path)
    assert not result.success and result.status_code == status
    assert satellites.download_error_text(result) == text
    assert not satellites.group_file("last-30-days", tmp_path).exists()


@pytest.mark.unit
@pytest.mark.parametrize(
    "error, text",
    [
        (requests.ConnectionError("no route"), "No network"),
        (requests.ConnectTimeout("slow"), "No answer from server"),
    ],
)
def test_network_error_text(tmp_path, monkeypatch, error, text):
    def get(*args, **kwargs):
        raise error

    monkeypatch.setattr(download_utils.requests, "get", get)
    result = satellites.download_group("visual", tmp_path)
    assert satellites.download_error_text(result) == text


@pytest.mark.unit
def test_web_message_names_each_group_with_its_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(satellites, "download_group", failed_like_404)
    write_groups(tmp_path, ["last-30-days"], [])
    result = satellites.refresh_groups(system_now(), True, tmp_path)
    message, error = web_satellites.refresh_message(result)
    assert message == ""
    assert error == "Launched in the last 30 days: CelesTrak has no data."


# ---------------------------------------------------------------------------
# Device texts
# ---------------------------------------------------------------------------


def list_screen(code="SA"):
    return SimpleNamespace(item_definition={"value": code})


def status_text(state, data):
    status = CatalogStatus(state, CatalogState.READY, data)
    return UIObjectList._get_catalog_status_message(list_screen(), status)[0]


@pytest.mark.unit
@pytest.mark.parametrize(
    "state, data, lines",
    [
        (CatalogState.DOWNLOADING, {"progress": None}, ["Downloading..."]),
        (CatalogState.CALCULATING, None, ["Calculating..."]),
        (CatalogState.ERROR, {"reason": "no_groups"}, ["No groups", "selected"]),
        (
            CatalogState.ERROR,
            {"reason": "failed", "groups": ["last-30-days"]},
            ["Download failed", "Last 30 days"],
        ),
        (
            CatalogState.ERROR,
            {"reason": "failed", "groups": ["visual", "stations", "amateur"]},
            ["Download failed", "Brightest", "and 2 more"],
        ),
        (CatalogState.ERROR, {"reason": "no_data"}, ["No data yet"]),
        (CatalogState.ERROR, {"reason": "too_old"}, ["Sets too old"]),
    ],
)
def test_empty_list_shows_the_catalog_state(state, data, lines):
    text = status_text(state, data)
    assert text.split("\n") == lines
    assert all(len(line) <= DEVICE_LINE_CHARS for line in lines)


@pytest.mark.unit
def test_filtered_list_says_how_many_satellites_the_catalog_has():
    status = CatalogStatus(CatalogState.READY, CatalogState.READY, {"total": 45})
    assert status_text(CatalogState.READY, {"total": 45}) is None
    lines = UIObjectList._no_match_lines(list_screen(), status)
    assert lines == ["45 satellites", "none match", "the filter"]
    plain = CatalogStatus(CatalogState.READY, CatalogState.READY, None)
    assert UIObjectList._no_match_lines(list_screen("NGC"), plain) == [
        "No objects",
        "match filter",
    ]


@pytest.fixture
def sat_dir(tmp_path, monkeypatch):
    directory = tmp_path / "satellites"
    monkeypatch.setattr(utils, "satellite_data_dir", directory)
    monkeypatch.setattr(sat_groups, "downloads", sat_groups.GroupDownloads())
    monkeypatch.setattr(UIModule, "message_until", 0.0)
    return directory


def fail_group(directory: Path, group: str) -> None:
    now = system_now()
    satellites.record_download_start(group, now, directory)
    satellites.record_download_end(group, now, failed_like_404(group), directory)


@pytest.mark.unit
def test_menu_marks_a_selected_group_whose_download_failed(sat_dir):
    write_groups(sat_dir, ["last-30-days", "visual"], ["visual"])
    menu = SimpleNamespace()
    assert sat_groups.failed_mark("last-30-days", menu) == ""
    fail_group(sat_dir, "last-30-days")
    fail_group(sat_dir, "amateur")
    assert sat_groups.failed_mark("last-30-days", menu) == "!"
    assert sat_groups.failed_mark("visual", menu) == ""
    # A group that is not selected has no mark.
    assert sat_groups.failed_mark("amateur", menu) == ""
    items = {item["value"]: item for item in sat_groups.menu_items()}
    assert items["last-30-days"]["name_suffix_callback"](menu) == "!"


@pytest.mark.unit
def test_select_of_a_failed_group_with_a_file_shows_the_reason(sat_dir):
    write_groups(sat_dir, ["visual"], ["visual", "stations"])
    fail_group(sat_dir, "stations")
    sat_groups.toggle_group(None, "stations", True)
    text = sat_groups.downloads.next_message()
    assert text == "Update failed\nStations\nGroup empty now"
    assert all(len(line) <= DEVICE_LINE_CHARS for line in text.split("\n"))


@pytest.mark.unit
def test_failed_group_download_message_has_the_reason(sat_dir):
    write_groups(sat_dir, ["visual"], ["visual"])
    with mock.patch.object(satellites, "download_group", failed_like_404):
        text = sat_groups.downloads._download("last-30-days", sat_dir)
    assert text == "Download failed\nLast 30 days\nGroup empty now"


@pytest.mark.unit
def test_download_message_shows_on_any_screen(sat_dir):
    # The main loop gives the MenuManager, whose message goes to the top
    # screen of the stack.
    screen = SimpleNamespace(
        message=mock.MagicMock(),
        display_class=SimpleNamespace(resX=128, resY=128),
    )
    sat_groups.downloads.post("Download failed\nLast 30 days\nGroup empty now")
    sat_groups.show_next_message(screen)
    text, seconds = screen.message.call_args.args
    assert text.startswith("Download failed")
    assert seconds == sat_groups.ERROR_MESSAGE_SECONDS
    box = screen.message.call_args.kwargs["size"]
    assert box[3] - box[1] >= 3 * 16
    # A second message waits for the end of the first.
    UIModule.message_until = 1e12
    sat_groups.downloads.post("Downloaded\nBrightest")
    sat_groups.show_next_message(screen)
    assert screen.message.call_count == 1


@pytest.mark.unit
def test_catalog_update_result_goes_to_the_listener(tmp_path, monkeypatch):
    monkeypatch.setattr(satellites, "download_group", failed_like_404)
    write_groups(tmp_path, ["last-30-days"], [])
    cat = satellite_catalog.SatelliteCatalog(
        SharedState(system_now()), data_directory=tmp_path, start_threads=False
    )
    results = []
    cat.on_refresh_done = results.append
    cat._user_refresh()
    assert [result.failed for result in results] == [("last-30-days",)]
    text = sat_groups.catalog_result_message(results[0])
    assert text == "Download failed\nLast 30 days\nGroup empty now"


def _toggle_groups(directory: str, groups: list, rounds: int) -> None:
    for _round in range(rounds):
        for group in groups:
            satellites.set_group_enabled(group, False, Path(directory))
            satellites.set_group_enabled(group, True, Path(directory))


@pytest.mark.unit
def test_two_processes_can_change_the_selection_at_the_same_time(tmp_path):
    """The web server and the device write selection.json. No change of one
    process may get lost, and no temporary file may stay."""
    first = ["amateur", "weather", "science"]
    second = ["geo", "gps-ops", "cubesat"]
    context = multiprocessing.get_context("spawn")
    workers = [
        context.Process(target=_toggle_groups, args=(str(tmp_path), groups, 15))
        for groups in (first, second)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(60)
        assert worker.exitcode == 0
    selected = set(satellites.selected_groups(tmp_path))
    assert set(first + second) <= selected
    leftovers = [
        p.name for p in tmp_path.iterdir() if p.name.startswith("selection.json.")
    ]
    assert leftovers == []
