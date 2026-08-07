"""Request-level regression tests for /gps/update (#569).

``gps_update()`` had no try/except at all, so a value ``float()`` could not
read reached the user as a 500::

    POST /gps/update  latitudeDecimal=51,3  -> 500  (location unchanged)
    POST /gps/update  latitudeDecimal=51.5  -> 302  (same value, saved)

#536 fixed this class for /locations but its helper never reached the GPS
page.  These tests pin the tolerant parse, the range checks, and that a
rejected form locks nothing at all.
"""

import pytest

from PiFinder import server as server_module


class RecordingQueue:
    """Captures what the route would hand to the GPS process."""

    def __init__(self):
        self.messages = []

    def put(self, message):
        self.messages.append(message)


@pytest.fixture
def gps_client(monkeypatch):
    # The route sleeps a second to let the GPS thread catch up
    monkeypatch.setattr(server_module.time, "sleep", lambda seconds: None)

    gps_queue = RecordingQueue()
    server = server_module.Server(gps_queue=gps_queue)
    server.app.testing = True
    client = server.app.test_client()
    with client.session_transaction() as session:
        session["authenticated"] = True
    return client, gps_queue


def gps_form(**overrides):
    form = {
        "latitudeDecimal": "51.5",
        "longitudeDecimal": "3.2",
        "altitude": "10",
        "date": "2026-08-02",
        "time": "21:30:00",
    }
    form.update(overrides)
    return form


def fixes(queue):
    return [message for kind, message in queue.messages if kind == "fix"]


@pytest.mark.unit
def test_comma_decimal_is_accepted(gps_client):
    client, queue = gps_client

    response = client.post("/gps/update", data=gps_form(latitudeDecimal="51,3"))

    assert response.status_code == 302
    assert fixes(queue)[0]["lat"] == 51.3


@pytest.mark.unit
def test_period_decimal_still_works(gps_client):
    client, queue = gps_client

    response = client.post("/gps/update", data=gps_form())

    assert response.status_code == 302
    fix = fixes(queue)[0]
    assert (fix["lat"], fix["lon"], fix["altitude"]) == (51.5, 3.2, 10.0)
    assert [kind for kind, _ in queue.messages] == ["fix", "time"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "overrides",
    [
        {"latitudeDecimal": "not-a-number"},
        {"latitudeDecimal": ""},
        {"latitudeDecimal": "91"},
        {"longitudeDecimal": "-181"},
        {"altitude": "99999"},
    ],
    ids=["garbage", "blank", "lat-too-high", "lon-too-low", "altitude-too-high"],
)
def test_invalid_position_is_reported_and_locks_nothing(gps_client, overrides):
    client, queue = gps_client

    response = client.post("/gps/update", data=gps_form(**overrides))

    assert response.status_code == 200
    assert queue.messages == []


@pytest.mark.unit
def test_rejected_form_comes_back_with_the_typed_values(gps_client):
    client, _ = gps_client

    response = client.post("/gps/update", data=gps_form(latitudeDecimal="ninety"))

    assert 'action="/gps/update"' in response.text
    assert 'value="ninety"' in response.text
    assert "must be a number" in response.text


@pytest.mark.unit
def test_unreadable_time_does_not_lock_a_partial_update(gps_client):
    """Position and time are parsed before either is sent, so a bad clock
    entry doesn't leave the location half-applied."""
    client, queue = gps_client

    response = client.post("/gps/update", data=gps_form(time="half past nine"))

    assert response.status_code == 200
    assert queue.messages == []
