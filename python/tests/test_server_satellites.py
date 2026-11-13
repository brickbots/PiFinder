"""Request tests for the satellite web pages."""

import datetime
import inspect
import io
import os
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

import PiFinder.satellites as satellites
import PiFinder.web_satellites as web_satellites
from PiFinder import server as server_module
from PiFinder.state import Location
from PiFinder.utils import satellite_data_dir

DATA = Path(__file__).parent / "data" / "satellites"
ISS_NORAD = 25544


class WebSharedState:
    """The part of the shared state that the satellite pages read."""

    def __init__(self, dt):
        self.dt = dt
        self._location = Location(
            lat=50.85, lon=4.35, altitude=50.0, lock=True, timezone="Europe/Brussels"
        )

    def datetime(self):
        return self.dt

    def location(self):
        return self._location


def use_directory(monkeypatch, directory):
    """Make ``directory`` the default data directory of each function."""
    for module in (satellites, web_satellites):
        for _name, function in inspect.getmembers(module, inspect.isfunction):
            defaults = function.__defaults__ or ()
            if any(value is satellite_data_dir for value in defaults):
                monkeypatch.setattr(
                    function,
                    "__defaults__",
                    tuple(
                        directory if value is satellite_data_dir else value
                        for value in defaults
                    ),
                )


def iss_epoch() -> datetime.datetime:
    elements, _errors = satellites.parse_elements((DATA / "25544.3le").read_text())
    return elements[0].epoch


@pytest.fixture
def web(tmp_path, monkeypatch):
    use_directory(monkeypatch, tmp_path)
    (tmp_path / "visual.tle").write_text((DATA / "visual.tle").read_text())
    (tmp_path / "stations.tle").write_text((DATA / "25544.3le").read_text())
    shared_state = WebSharedState(iss_epoch() + datetime.timedelta(days=1))
    server = server_module.Server(shared_state=shared_state)
    server.app.testing = True
    client = server.app.test_client()
    with client.session_transaction() as session:
        session["authenticated"] = True
    return client, shared_state, tmp_path


def redirect_query(response) -> dict:
    assert response.status_code == 302
    return parse_qs(urlparse(response.headers["Location"]).query)


@pytest.mark.unit
def test_page_shows_the_sky_table_and_the_check_boxes(web):
    client, _shared_state, _directory = web
    response = client.get("/satellites")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "In the sky now" in page
    assert 'name="kind" value="group"' in page
    assert 'id="satellite_time_note"' not in page


@pytest.mark.unit
def test_pages_say_when_the_time_is_not_from_the_gps(web, monkeypatch):
    client, shared_state, _directory = web
    shared_state.dt = None
    page = client.get("/satellites").get_data(as_text=True)
    assert 'id="satellite_time_note"' in page
    assert "no GPS time" in page
    # The system clock is far from the epoch of the fixture element sets.
    monkeypatch.setattr(satellites, "MAX_ELEMENT_AGE_DAYS", 1e6)
    response = client.get(f"/satellites/{ISS_NORAD}")
    assert response.status_code == 200
    assert 'id="satellite_time_note"' in response.get_data(as_text=True)


@pytest.mark.unit
def test_satellite_page_has_no_note_with_gps_time(web):
    client, _shared_state, _directory = web
    response = client.get(f"/satellites/{ISS_NORAD}")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert 'id="satellite_time_note"' not in page
    assert "Show on PiFinder" in page


@pytest.mark.unit
def test_enable_route_stores_the_selection(web):
    client, _shared_state, directory = web
    response = client.post(
        "/satellites/enable", data={"kind": "group", "id": "visual", "enabled": "0"}
    )
    assert "msg" in redirect_query(response)
    assert not satellites.load_selection(directory).group_enabled("visual")
    page = client.get("/satellites").get_data(as_text=True)
    assert page.count(" checked") == 1

    client.post(
        "/satellites/enable", data={"kind": "group", "id": "visual", "enabled": "1"}
    )
    assert satellites.load_selection(directory).group_enabled("visual")

    response = client.post(
        "/satellites/enable", data={"kind": "group", "id": "other", "enabled": "0"}
    )
    assert "err" in redirect_query(response)


@pytest.mark.unit
def test_disabled_satellite_page_has_no_show_button(web):
    client, _shared_state, directory = web
    satellites.set_group_enabled("visual", False, directory)
    satellites.set_group_enabled("stations", False, directory)
    page = client.get(f"/satellites/{ISS_NORAD}").get_data(as_text=True)
    assert 'id="satellite_disabled_note"' in page
    assert "Show on PiFinder" not in page
    response = client.post(f"/satellites/show/{ISS_NORAD}")
    assert "err" in redirect_query(response)


@pytest.mark.unit
def test_upload_larger_than_the_limit_is_refused(web):
    client, _shared_state, directory = web
    text = (DATA / "25544.3le").read_text()
    padding = "#" * (web_satellites.MAX_UPLOAD_BYTES + 1)
    response = client.post(
        "/satellites/add",
        data={"file": (io.BytesIO((text + padding).encode()), "big.tle")},
        content_type="multipart/form-data",
    )
    assert "too large" in redirect_query(response)["err"][0]
    assert satellites.load_user_elements(directory) == []

    response = client.post(
        "/satellites/add",
        data={"file": (io.BytesIO(text.encode()), "iss.tle")},
        content_type="multipart/form-data",
    )
    assert "msg" in redirect_query(response)
    assert [e.norad_id for e in satellites.load_user_elements(directory)] == [ISS_NORAD]


@pytest.mark.unit
def test_refresh_route_refuses_a_download_after_a_recent_one(web, monkeypatch):
    client, _shared_state, _directory = web
    calls = []

    def download(group, directory=None, progress_callback=None):
        calls.append(group)
        return satellites.DownloadResult(True, None, None)

    monkeypatch.setattr(satellites, "download_group", download)
    # The fixture wrote the group files a moment ago.
    response = client.post("/satellites/refresh")
    assert "Wait 5 min" in redirect_query(response)["err"][0]
    assert calls == []


class RecordedDownloads:
    """Replaces the network. Writes the ISS set as the group file."""

    def __init__(self):
        self.groups = []

    def __call__(self, group, directory=None, progress_callback=None):
        self.groups.append(group)
        satellites.group_file(group, directory).write_text(
            (DATA / "25544.3le").read_text()
        )
        return satellites.DownloadResult(True, None, None)


def make_old(path: Path) -> None:
    when = time.time() - 3600.0
    os.utime(path, (when, when))


@pytest.mark.unit
def test_page_has_a_row_and_an_update_button_for_each_selected_group(web):
    client, _shared_state, _directory = web
    page = client.get("/satellites").get_data(as_text=True)
    for name in satellites.CELESTRAK_GROUPS:
        assert f'name="id" value="{name}"' in page
    assert page.count('name="group" value=') == len(satellites.DEFAULT_GROUPS)
    assert 'name="group" value="visual"' in page
    assert "Update selected" in page
    assert page.count("Large group: the pass prediction takes long on a Pi") == 4
    assert "not downloaded" in page


@pytest.mark.unit
def test_update_route_downloads_one_group(web, monkeypatch):
    client, _shared_state, directory = web
    downloads = RecordedDownloads()
    monkeypatch.setattr(satellites, "download_group", downloads)
    make_old(directory / "visual.tle")
    make_old(directory / "stations.tle")

    response = client.post("/satellites/refresh", data={"group": "visual"})
    assert redirect_query(response)["msg"] == ["Downloaded: visual"]
    assert downloads.groups == ["visual"]

    response = client.post("/satellites/refresh", data={"group": "visual"})
    assert "Wait 5 min" in redirect_query(response)["err"][0]
    assert downloads.groups == ["visual"]

    response = client.post("/satellites/refresh")
    query = redirect_query(response)
    assert query["msg"] == ["Downloaded: stations"]
    assert "visual" in query["err"][0] and "Wait 5 min" in query["err"][0]
    assert downloads.groups == ["visual", "stations"]

    response = client.post("/satellites/refresh", data={"group": "amateur"})
    assert "err" in redirect_query(response)
    response = client.post("/satellites/refresh", data={"group": "no-such-group"})
    assert "err" in redirect_query(response)
    assert downloads.groups == ["visual", "stations"]


@pytest.mark.unit
def test_selecting_a_group_without_a_file_downloads_it(web, monkeypatch):
    client, _shared_state, directory = web
    downloads = RecordedDownloads()
    monkeypatch.setattr(satellites, "download_group", downloads)
    response = client.post(
        "/satellites/enable", data={"kind": "group", "id": "amateur", "enabled": "1"}
    )
    query = redirect_query(response)
    assert "Downloaded: amateur" in query["msg"][0]
    assert "err" not in query
    assert downloads.groups == ["amateur"]
    assert satellites.selected_groups(directory) == ("visual", "stations", "amateur")
    page = client.get("/satellites").get_data(as_text=True)
    assert 'name="group" value="amateur"' in page

    # A group with a file and a group that the user deselects do not download.
    client.post(
        "/satellites/enable", data={"kind": "group", "id": "visual", "enabled": "0"}
    )
    client.post(
        "/satellites/enable", data={"kind": "group", "id": "visual", "enabled": "1"}
    )
    client.post(
        "/satellites/enable", data={"kind": "group", "id": "weather", "enabled": "0"}
    )
    assert downloads.groups == ["amateur"]


@pytest.mark.unit
def test_page_lists_corrected_sets_with_a_delete_route(web):
    client, shared_state, directory = web
    page = client.get("/satellites").get_data(as_text=True)
    assert "corrected_satellite_table" not in page
    element = satellites.load_all_elements(shared_state.dt, directory)[0]
    satellites.save_corrected_element(element, shared_state.dt, directory)
    page = client.get("/satellites").get_data(as_text=True)
    assert "corrected_satellite_table" in page
    assert 'name="kind" value="corrected"' in page

    response = client.post(f"/satellites/corrected/delete/{element.norad_id}")
    assert "msg" in redirect_query(response)
    assert satellites.load_corrected_elements(directory) == []
    response = client.post(f"/satellites/corrected/delete/{element.norad_id}")
    assert "err" in redirect_query(response)
