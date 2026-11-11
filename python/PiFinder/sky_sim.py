"""A closed-loop sky simulator for mount control tests.

It makes plate solves from the position of an INDI mount (normally the INDI
telescope simulator) instead of from camera frames, so goto, refine, sync
and drift compensation behave as on a real sky. The integrator takes its
solves from here instead of the solver while it runs.

Model:
- The reported mount position includes the syncs. The simulator keeps the
  sum of the sync jumps, so physical = reported - syncs. A sync shows as a
  jump of the reported position while the mount is not slewing. The
  simulator watches every position update of the driver for this, so a
  short slew between two solves still counts as a slew.
- The telescope points at physical + pointing error (a fixed offset that
  a scenario can change) + noise.
- While the mount slews (state Busy) a solve fails: the frame has blur.
- A solve also fails at the failure rate (clouds, too few stars).

The settings come from a JSON file. "events" change settings at a time in
seconds after the start, for example clouds:

    {"rate_hz": 1.0, "offset_ra_deg": 1.5, "offset_dec_deg": -0.8,
     "noise_arcsec": 10, "failure_rate": 0.05, "seed": 1,
     "events": [{"t": 40, "failure_rate": 1.0}, {"t": 60, "failure_rate": 0.05}]}
"""

import dataclasses
import datetime
import json
import logging
import math
import random
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Union

from PiFinder import calc_utils
from PiFinder.indi_client import TELESCOPE_INTERFACE, IndiClient, IndiProperty
from PiFinder.types.positioning import (
    FailedSolve,
    Pointing,
    SolveDiagnostics,
    SuccessfulSolve,
)

logger = logging.getLogger("SkySim")

POSITION = "EQUATORIAL_EOD_COORD"
# A jump of the reported position larger than this while the mount does not
# slew is a sync. Sidereal tracking keeps the EOD position still.
SYNC_JUMP_DEG = 0.02


@dataclasses.dataclass
class SkySimSettings:
    rate_hz: float = 1.0
    offset_ra_deg: float = 1.5
    offset_dec_deg: float = -0.8
    noise_arcsec: float = 10.0
    failure_rate: float = 0.0
    roll_deg: float = 0.0
    seed: Optional[int] = None
    indi_host: str = "localhost"
    indi_port: int = 7624
    events: list = dataclasses.field(default_factory=list)

    @classmethod
    def load(cls, source: Union[str, Path, None]) -> "SkySimSettings":
        """From a JSON file, or the defaults for None or "default"."""
        if source is None or str(source) == "default":
            return cls()
        values = json.loads(Path(source).read_text())
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = set(values) - known
        if unknown:
            raise ValueError(f"unknown sky simulator settings: {sorted(unknown)}")
        return cls(**values)


class SkySimulator:
    """Makes SuccessfulSolve/FailedSolve messages from the mount position."""

    def __init__(
        self,
        settings: SkySimSettings,
        now_utc: Callable[[], Optional[datetime.datetime]],
        client: Optional[IndiClient] = None,
        clock: Callable[[], float] = time.time,
    ):
        self.settings = settings
        self._now_utc = now_utc
        self._clock = clock
        self._random = random.Random(settings.seed)
        self._client = client or IndiClient(settings.indi_host, settings.indi_port)
        self._client.add_listener(self._on_property)
        self._lock = threading.Lock()
        self._device: Optional[str] = None
        self._start: Optional[float] = None
        self._next_due = 0.0
        self._events = sorted(settings.events, key=lambda e: e["t"])
        self._last_reported: Optional[tuple[float, float]] = None
        self._was_busy = False
        # The sum of the sync jumps in RA and Dec (degrees).
        self.sync_ra = 0.0
        self.sync_dec = 0.0

    # Mount

    def _mount_position(self) -> Optional[tuple[float, float, str]]:
        """The reported JNow RA/Dec in degrees and the property state."""
        if not self._client.is_connected() and not self._client.connect(timeout=1.0):
            return None
        if self._device is None:
            for device in self._client.devices():
                interface = self._client.device_interface(device)
                if interface is not None and interface & TELESCOPE_INTERFACE:
                    self._device = device
                    logger.info("Sky simulator follows %s", device)
                    break
        if self._device is None:
            return None
        prop = self._client.get_property(self._device, POSITION)
        if prop is None:
            return None
        ra = prop.elements.get("RA")
        dec = prop.elements.get("DEC")
        if not isinstance(ra, float) or not isinstance(dec, float):
            return None
        return ra * 15.0, dec, prop.state

    def _on_property(
        self,
        event: str,
        device: str,
        name: Optional[str],
        prop: Optional[IndiProperty],
    ) -> None:
        """Every position update of the mount (client reader thread)."""
        if event not in ("def", "set") or name != POSITION or prop is None:
            return
        if self._device is not None and device != self._device:
            return
        ra = prop.elements.get("RA")
        dec = prop.elements.get("DEC")
        if isinstance(ra, float) and isinstance(dec, float):
            with self._lock:
                self._track_syncs(ra * 15.0, dec, prop.state == "Busy")

    def _track_syncs(self, ra: float, dec: float, busy: bool) -> None:
        """Add a jump of the reported position while the mount stands still
        to the sync record."""
        if self._last_reported is not None and not busy and not self._was_busy:
            d_ra = (ra - self._last_reported[0] + 180.0) % 360.0 - 180.0
            d_dec = dec - self._last_reported[1]
            if abs(d_ra) > SYNC_JUMP_DEG or abs(d_dec) > SYNC_JUMP_DEG:
                self.sync_ra += d_ra
                self.sync_dec += d_dec
                logger.info("Sync seen: RA %+.4f°, Dec %+.4f°", d_ra, d_dec)
        self._last_reported = (ra, dec)
        self._was_busy = busy

    # Scenario

    def _apply_events(self, elapsed: float) -> None:
        while self._events and self._events[0]["t"] <= elapsed:
            event = self._events.pop(0)
            for key, value in event.items():
                if key != "t" and hasattr(self.settings, key):
                    setattr(self.settings, key, value)
            logger.info("Sky simulator event at %.0f s: %s", elapsed, event)

    # Solves

    def true_pointing(self, reported_ra: float, reported_dec: float) -> tuple:
        """Where the telescope points (JNow degrees), without noise."""
        with self._lock:
            sync_ra, sync_dec = self.sync_ra, self.sync_dec
        ra = reported_ra - sync_ra + self.settings.offset_ra_deg
        dec = reported_dec - sync_dec + self.settings.offset_dec_deg
        return ra % 360.0, max(-90.0, min(90.0, dec))

    def next_message(self) -> Union[SuccessfulSolve, FailedSolve, None]:
        """The next solve when one is due, else None."""
        now = self._clock()
        if self._start is None:
            self._start = now
            self._next_due = now
        if now < self._next_due:
            return None
        self._next_due = now + 1.0 / max(self.settings.rate_hz, 0.01)
        self._apply_events(now - self._start)

        mount = self._mount_position()
        if mount is None:
            return None
        ra, dec, state = mount
        busy = state == "Busy"
        if busy or self._random.random() < self.settings.failure_rate:
            return FailedSolve(
                diagnostics=SolveDiagnostics(Matches=0),
                last_solve_attempt=now,
                last_solve_success=None,
            )

        true_ra, true_dec = self.true_pointing(ra, dec)
        noise = self.settings.noise_arcsec / 3600.0
        true_dec += self._random.gauss(0.0, noise)
        cos_dec = max(math.cos(math.radians(true_dec)), 1e-6)
        true_ra += self._random.gauss(0.0, noise) / cos_dec
        dt = self._now_utc() or datetime.datetime.now(datetime.timezone.utc)
        j2000_ra, j2000_dec = calc_utils.jnow_to_j2000(true_ra % 360.0, true_dec, dt)
        pointing = Pointing(RA=j2000_ra, Dec=j2000_dec, Roll=self.settings.roll_deg)
        return SuccessfulSolve(
            camera=pointing,
            aligned=pointing,
            imu_anchor=None,
            last_solve_attempt=now,
            last_solve_success=now,
            diagnostics=SolveDiagnostics(Matches=30, RMSE=noise * 3600.0),
        )
