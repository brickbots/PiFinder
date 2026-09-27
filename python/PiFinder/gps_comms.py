#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Publishing of GPS comms events - the liveness half of what the GPS process
reports, as opposed to the fix and time it exists to produce.

An *event* is anything the parser yields: a decoded message, or a marker
standing in for a frame that arrived but could not be decoded. The STATUS
screen's comms row shows the most recent event's name and how long ago it
arrived, which is what separates "nothing is arriving" from "bytes are
arriving that we cannot read". See docs/ax/gps/CONTEXT.md.

The GPS process publishes names; the main process stamps them on arrival.

All three GPS backends publish through this module so the row means the same
thing whichever one is running.
"""

import time
from typing import Optional

# How often comms events are forwarded onto gps_queue, at most. A resync storm
# can yield markers far faster than real messages arrive, and the .ubx replay
# path runs with wait=0, so an uncapped publish would put the queue depth at
# the mercy of how badly the link is behaving. 20 Hz is well past perceptible
# against a 30 fps redraw. This caps *reporting*, not parsing.
MAX_COMMS_RATE_HZ = 20


class CommsPublisher:
    """Forwards GPS event names onto gps_queue, rate-capped.

    Only the name is published. The arrival time is stamped by the main
    process when it drains the queue, with its own monotonic clock, because
    that is the process the STATUS screen renders in - a stamp taken here
    would have to survive a comparison against a *different* process's clock,
    and ``time.monotonic()``'s reference point is explicitly undefined (on
    macOS it is process start, so the age comes out inflated by however long
    after main the GPS process happened to start).

    The clock read here is only ever used for the rate cap, which measures an
    interval between two readings in this one process - the use the standard
    library does guarantee.
    """

    def __init__(self, gps_queue, clock=time.monotonic, max_rate_hz=MAX_COMMS_RATE_HZ):
        self._gps_queue = gps_queue
        self._clock = clock
        self._min_interval = 1.0 / max_rate_hz
        self._last_published = None

    def publish(self, event_name: str, now: Optional[float] = None) -> bool:
        """Publish `event_name` as having arrived at `now` (default: read the
        clock). Returns False if the event was suppressed by the rate cap."""
        if not event_name:
            return False
        if now is None:
            now = self._clock()
        if (
            self._last_published is not None
            and now - self._last_published < self._min_interval
        ):
            return False
        self._last_published = now
        self._gps_queue.put(("comms", event_name))
        return True
