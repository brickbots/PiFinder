"""Dispatch-level tests for PiFinder.gps_ubx.process_messages.

These cover how the message classes combine into the published (seen, used)
satellite counts, as opposed to test_gps_ubx_parser.py which covers decoding a
single message.
"""

import asyncio

import pytest

from PiFinder import gps_comms, gps_ubx


class FakeQueue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)

    def qsize(self):
        return 0


class FakeClock:
    """Manually advanced monotonic stand-in."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TickingClock:
    """Monotonic stand-in that advances on every read.

    The comms publisher is rate-capped, so a frozen clock suppresses every
    event after the first; use this where the test is about what gets
    published rather than about the cap itself.
    """

    def __init__(self, step=1.0):
        self.now = 1000.0
        self.step = step

    def __call__(self):
        value = self.now
        self.now += self.step
        return value


def run_messages(messages, clock=None, tag="satellites"):
    """Feed `messages` through process_messages, return the payloads it
    published under `tag` ("satellites" counts, or "comms" events)."""
    gps_ubx.sats[0] = 0
    gps_ubx.sats[1] = 0
    gps_queue = FakeQueue()
    console_queue = FakeQueue()

    async def iterator():
        for msg in messages:
            yield msg

    asyncio.run(
        gps_ubx.process_messages(
            iterator,
            gps_queue,
            console_queue,
            error_info={},
            clock=clock or FakeClock(),
        )
    )
    return [content for name, content in gps_queue.items if name == tag]


def nav_sat(seen, used):
    sats = [{"used": True} for _ in range(used)]
    sats += [{"used": False} for _ in range(seen - used)]
    return {"class": "NAV-SAT", "nSat": seen, "satellites": sats}


def svinfo(seen, used):
    return {"class": "NAV-SVINFO", "nSat": seen, "uSat": used}


@pytest.mark.unit
def test_nav_sat_preferred_over_svinfo_while_fresh():
    clock = FakeClock()
    published = run_messages([nav_sat(9, 7), svinfo(20, 0)], clock=clock)

    # The SVINFO message is suppressed: NAV-SAT arrived moments ago.
    assert published == [(9, 7)]


@pytest.mark.unit
def test_svinfo_resumes_when_nav_sat_goes_stale():
    """A one-off NAV-SAT must not silence the SVINFO fallback forever.

    Regression test: got_sat_update used to latch True on the first NAV-SAT
    and was never reset, freezing the counts for the life of the connection.
    """
    clock = FakeClock()

    class StaleAfterFirst:
        """Advance past the preference window once NAV-SAT has been seen."""

        def __init__(self):
            self.calls = 0

        def __call__(self):
            self.calls += 1
            value = clock.now
            if self.calls == 1:
                clock.advance(gps_ubx.NAV_SAT_PREFERENCE_TIMEOUT + 1)
            return value

    published = run_messages([nav_sat(9, 7), svinfo(11, 8)], clock=StaleAfterFirst())

    assert published == [(9, 7), (11, 8)]


@pytest.mark.unit
def test_nav_pvt_used_count_raises_the_seen_floor():
    """NAV-PVT carries only numSV; seen must not read below it."""
    published = run_messages([{"class": "NAV-PVT", "numSV": 9}])

    assert published == [(9, 9)]


@pytest.mark.unit
def test_nav_pvt_does_not_lower_a_known_seen_count():
    clock = FakeClock()
    published = run_messages(
        [nav_sat(12, 9), {"class": "NAV-PVT", "numSV": 9}], clock=clock
    )

    assert published == [(12, 9), (12, 9)]


@pytest.mark.unit
def test_nav_sol_used_count_raises_the_seen_floor():
    published = run_messages([{"class": "NAV-SOL", "satellites": 6}])

    assert published == [(6, 6)]


# --- Comms events ------------------------------------------------------------
# Liveness reporting: every event the parser yields is named on gps_queue, which
# is what lets the STATUS comms row tell a dead link from an undecodable one.
# Only the name travels - the main process stamps arrival with its own clock.


@pytest.mark.unit
def test_every_event_is_published_by_name():
    published = run_messages(
        [{"class": "NAV-DOP", "hdop": 1.0, "pdop": 2.0}, {"class": "NAV-EOE"}],
        clock=TickingClock(),
        tag="comms",
    )

    assert published == ["NAV-DOP", "NAV-EOE"]


@pytest.mark.unit
def test_events_the_dispatcher_ignores_still_count_as_liveness():
    """NAV-POSECEF has no branch in the dispatch chain, but the link is
    demonstrably alive when one arrives."""
    published = run_messages(
        [{"class": "NAV-POSECEF"}], clock=TickingClock(), tag="comms"
    )

    assert published == ["NAV-POSECEF"]


@pytest.mark.unit
def test_markers_are_published_like_any_other_event():
    """A frame we cannot decode is exactly the case the row exists for, so it
    must reach the queue even though the dispatch chain ignores it."""
    published = run_messages(
        [{"class": "?CKSUM"}, {"class": "?0122"}],
        clock=TickingClock(),
        tag="comms",
    )

    assert published == ["?CKSUM", "?0122"]


@pytest.mark.unit
def test_markers_do_not_disturb_the_satellite_counts():
    published = run_messages(
        [svinfo(11, 8), {"class": "?CKSUM"}, {"class": "?0122"}],
        clock=TickingClock(),
    )

    assert published == [(11, 8)]


@pytest.mark.unit
def test_rate_cap_suppresses_a_burst():
    """A resync storm yields markers far faster than real messages arrive; the
    cap bounds queue traffic without slowing parsing."""
    burst = [{"class": "?CKSUM"} for _ in range(50)]
    published = run_messages(burst, clock=FakeClock(), tag="comms")

    # FakeClock never advances, so everything after the first is inside the
    # minimum interval.
    assert published == ["?CKSUM"]


@pytest.mark.unit
def test_rate_cap_releases_once_the_interval_passes():
    clock = TickingClock(step=2.0 / gps_comms.MAX_COMMS_RATE_HZ)
    published = run_messages(
        [{"class": "?CKSUM"} for _ in range(4)], clock=clock, tag="comms"
    )

    assert len(published) == 4
