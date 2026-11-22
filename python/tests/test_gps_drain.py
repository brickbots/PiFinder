import queue

import pytest

from PiFinder.main import drain_gps_queue


def _drain(messages, pending=None):
    q: queue.Queue = queue.Queue()
    for m in messages:
        q.put(m)
    pending = {} if pending is None else pending
    calls = drain_gps_queue(q, pending)
    assert q.empty()
    return pending, calls


def _fix(err):
    return {"lat": 50.0, "lon": 4.0, "altitude": 10, "error_in_m": err}


@pytest.mark.unit
def test_keeps_the_fix_with_the_smallest_error():
    pending, _ = _drain([("fix", _fix(30)), ("fix", _fix(5)), ("fix", _fix(12))])
    assert pending["fix"]["error_in_m"] == 5


@pytest.mark.unit
def test_keeps_the_newest_satellites_and_comms():
    pending, _ = _drain(
        [("satellites", (3, 8)), ("comms", 1), ("satellites", (5, 9)), ("comms", 2)]
    )
    assert pending["satellites"] == (5, 9)
    assert pending["comms"] == 2


@pytest.mark.unit
def test_time_force_wins_over_a_later_plain_time():
    pending, _ = _drain([("time_force", "t1"), ("time", "t2")])
    assert pending["time"] == ("t2", True)
    pending, _ = _drain([("time", "t1"), ("time", "t2")])
    assert pending["time"] == ("t2", False)


@pytest.mark.unit
def test_reset_acts_in_place_and_drops_an_older_fix():
    pending, calls = _drain([("fix", _fix(5)), ("reset", None), ("fix", _fix(20))])
    assert calls == ["reset"]
    assert pending["fix"]["error_in_m"] == 20


@pytest.mark.unit
def test_reset_datetime_drops_an_older_time():
    pending, calls = _drain([("time", "t1"), ("reset_datetime", None)])
    assert calls == ["reset_datetime"]
    assert "time" not in pending


@pytest.mark.unit
def test_pending_from_an_earlier_loop_stays():
    pending, _ = _drain([("comms", 1)])
    pending, _ = _drain([("fix", _fix(5))], pending)
    assert pending["comms"] == 1 and pending["fix"]["error_in_m"] == 5
