"""A mount for the tests of the mount control logic: mocked mount methods,
a fixed location and a clock of its own."""

import datetime
from queue import Queue
from typing import Collection, Optional
from unittest.mock import Mock

from PiFinder import track_rates
from PiFinder.mountcontrol_interface import MountControlBase, MountControlPhases
from PiFinder.state import Location, SharedStateObj

LOCATION = Location(lat=50.85, lon=4.35, altitude=50.0, lock=True)


class FakeMount(MountControlBase):
    """MountControlBase with mocked mount methods.

    ``rates_ok`` is the result of set_track_rates. apply_track_rate accepts
    the rates in ``supported``. ``dt`` is the PiFinder time, and ``now`` the
    clock of a follow.
    """

    def __init__(
        self,
        rates_ok: bool = True,
        supported: Collection[str] = track_rates.TRACK_RATES,
        dt: Optional[datetime.datetime] = None,
    ):
        shared_state = Mock(spec=SharedStateObj)
        shared_state.location.return_value = LOCATION
        shared_state.solution.return_value = None
        shared_state.datetime.return_value = dt
        super().__init__(Queue(), Queue(), shared_state)
        self.stop_mount = Mock(return_value=True)
        self.move_mount_to_target = Mock(return_value=True)
        self.is_mount_moving = Mock(return_value=True)
        self.set_track_rates = Mock(return_value=rates_ok)
        self.restore_sidereal_tracking = Mock()
        self.apply_track_rate = Mock(side_effect=lambda rate: rate in supported)
        self.notify = Mock()
        self.state = MountControlPhases.MOUNT_TRACKING
        self.now = 0.0
        self.clock = lambda: self.now

    def command(self, command: dict) -> None:
        for _step in self._process_command(command):
            pass

    def phase(self) -> None:
        for _step in self._process_phase():
            pass
