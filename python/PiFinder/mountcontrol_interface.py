# (C) 2025 Jens Scheidtmann
#
# This file is part of PiFinder.
#
# PiFinder is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import dataclasses
import datetime
import logging
import math
from enum import Enum, auto
import queue
from multiprocessing import Queue
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Generator, Iterator, Optional, Any

from PiFinder import calc_utils, satellites
from PiFinder import target_follow, track_rates
from PiFinder.target_follow import FollowStage, TargetFollow, angular_distance
from PiFinder.state import SharedStateObj
from PiFinder.types.mount import (
    ROTATION_DONE,
    ROTATION_FAILED,
    ROTATION_REFUSED,
    ROTATION_STALE,
    ROTATION_STOPPED,
    ROTATION_TIMEOUT,
    ROTATION_TURNING,
    MountStatus,
    format_step,
)
from PiFinder.utils import satellite_data_dir

import PiFinder.i18n  # noqa: F401

# Mypy i8n fix
if TYPE_CHECKING:

    def _(a) -> Any:
        return a


logger = logging.getLogger("MountControl")

""" Module for controlling the telescope mount. 

The MountControlBase class provides the main control loop and shared logic for mount control. 
The split of responsibilities between the base class and subclasses is as follows:

- The MountControlBase class manages the MountControlPhase and calls the appropriate methods on the subclass based on the current phase.
- The subclass is responsible for implementing the hardware-specific logic for each phase, such as initializing the mount, moving to a target.
  This also involves handling mount state, such as parked and unparked.

"""


class MountControlPhases(Enum):
    """
    Enumeration representing the various phases and states of controlling the telescope mount.

    States:
        MOUNT_INIT_TELESCOPE:
            Telescope needs to be initialized, connected to, settings need to be set, encoders switched on, unparked etc.
        MOUNT_STOPPED:
            The mount is stopped and is not tracking or moving. Basically we wait for user selection of a target.
            This is the state after initialization and before target acquisition.
        MOUNT_TARGET_ACQUISITION_MOVE:
            The user has selected a target and the mount being commanded to move to it. The mount slews to the selected target.
            and we wait for it to finish slewing. This state may be entered from MOUNT_TARGET_ACQUISITION_REFINE multiple times.
        MOUNT_TARGET_ACQUISITION_REFINE:
            The mount believes it has acquired the target, and now we use PiFinder's platesolved position to refine its position and put
            the target into the center of the field of view.
        MOUNT_DRIFT_COMPENSATION:
            We have reached the target and put it in the center of the field of view. The mount is tracking and
            we are compensating for drift (due to polar alignment being off).
        MOUNT_TRACKING:
            The mount is tracking the sky but we are not doing drift compensation. This is entered, if the user moves the telescope manually.
        MOUNT_SPIRAL_SEARCH:
            The mount has been commanded to a spiral search pattern to find a target.
        MOUNT_TARGET_FOLLOW:
            The mount follows a moving target (see target_follow.py): a goto ahead
            of the satellite, then custom track rates or repeated gotos.
        MOUNT_RA_ROTATION:
            The mount turns only its RA axis by a set angle, for the polar
            alignment. Then it returns to MOUNT_TRACKING, or to
            MOUNT_STOPPED if it was stopped before.

    Note that a user interaction may at any time move the mount back to MOUNT_STOPPED, or put it into MOUNT_TRACKING.
    Once in drift compensation mode, the user may also select a new target, which will move the phase to MOUNT_TARGET_ACQUISITION_MOVE.
    Any error condition should actively abort any movement and set the state to MOUNT_INIT_TELESCOPE.

    This enum is used in the main control loop to decide on what action to take next.
    """

    MOUNT_UNKNOWN = auto()
    MOUNT_INIT_TELESCOPE = auto()
    MOUNT_STOPPED = auto()
    MOUNT_TARGET_ACQUISITION_MOVE = auto()
    MOUNT_TARGET_ACQUISITION_REFINE = auto()
    MOUNT_DRIFT_COMPENSATION = auto()
    MOUNT_TRACKING = auto()
    MOUNT_SPIRAL_SEARCH = auto()
    MOUNT_TARGET_FOLLOW = auto()
    MOUNT_RA_ROTATION = auto()


class MountDirections(Enum):
    """Base class for mount directions enumerations."""

    pass


class MountDirectionsAltAz(MountDirections):
    """
    Enumeration representing the possible manual movement directions for an equatorial mount.

    Directions:
        UP: Move the mount upwards (increasing Alt).
        DOWN: Move the mount downwards (decreasing Alt).
        LEFT: Move the mount left (decreasing Azimuth).
        RIGHT: Move the mount right (increasing Azimuth).
    """

    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()


class MountDirectionsEquatorial(MountDirections):
    """
    Enumeration representing the possible manual movement directions for an equatorial mount.

    Directions:
        NORTH: Move the mount North (increasing Declination).
        SOUTH: Move the mount South (decreasing Declination).
        EAST: Move the mount East (increasing Right Ascension).
        WEST: Move the mount West (decreasing Right Ascension).
    """

    NORTH = auto()
    SOUTH = auto()
    EAST = auto()
    WEST = auto()


# The mount process writes the status at once when the phase or the step
# changes, at most this often when only the distance changes, and at least
# this often as a sign of life.
STATUS_DISTANCE_PERIOD_S = 1.0
# A continuous move (a held arrow) stops after this time, if the release
# never comes.
MAX_MOTION_S = 30.0
STATUS_HEARTBEAT_S = 2.0
# Drift compensation fits a line when the solves span this part of the
# drift window.
DRIFT_WINDOW_FILL = 0.8
# An RA rotation for the polar alignment stops after this time.
RA_ROTATION_TIMEOUT_S = 90.0
# The smallest and the largest RA rotation of one command.
RA_ROTATION_MIN_DEG = 5.0
RA_ROTATION_MAX_DEG = 45.0
# Limits of an RA rotation. The hour angle stays on its side of the
# meridian (no pier flip), this far from the meridian at the end of a turn
# toward it, and at most this far from it.
RA_ROTATION_MERIDIAN_MARGIN_DEG = 3.0
RA_ROTATION_MAX_HA_DEG = 85.0
# The telescope points at least this high at both ends of a rotation.
RA_ROTATION_MIN_ALT_DEG = 15.0
# The mount can turn this much more than the angle before it stands still.
RA_ROTATION_OVERSHOOT_DEG = 6.0
# A rotation stops when the mount sends no position for this time.
RA_ROTATION_STALE_S = 3.0
# A rotation stops when the RA moved this much against the direction.
RA_ROTATION_WRONG_WAY_DEG = 2.0
# After the stop, the mount is still when its RA changed less than
# RA_ROTATION_STILL_DEG for RA_ROTATION_STILL_S. The wait ends after
# RA_ROTATION_STILL_TIMEOUT_S.
RA_ROTATION_STILL_DEG = 0.01
RA_ROTATION_STILL_S = 2.0
RA_ROTATION_STILL_TIMEOUT_S = 15.0
# While no axis has a significant drift, the drift window grows to this
# length (seconds). Then the data is cleared and a new window starts.
DRIFT_WINDOW_MAX_S = 60.0
# The fit needs at least this many solves.
DRIFT_MIN_SOLVES = 10
# A drift is significant when its slope is at least this many standard
# errors of the slope. The test runs again at each solve while the window
# grows, so the limit is above the usual 3. With 2" noise and no drift,
# about one 60 s window in 30 (1 solve/s) or in 100 (4 solves/s) gives a
# correction, and that correction is below 0.6"/s.
DRIFT_SIGNIFICANCE_SE = 4.0
# A drift on the sky below this (degrees/second, 0.05"/s) gets no
# correction. It does not show in an eyepiece.
DRIFT_MIN_CORRECTION_DEG_S = 0.05 / 3600.0
# A correction cancels this part of the measured drift. A gain below 1
# keeps the noise of the slope from an overshoot.
DRIFT_CORRECTION_GAIN = 0.7


def track_rate_label(rate: str) -> str:
    """Short label of a non-sidereal track rate, for the status line."""
    return {track_rates.LUNAR: _("Lunar"), track_rates.SOLAR: _("Solar")}.get(rate, "")


def _follow_correction(offset_deg: float) -> float:
    """The rate in degrees per second that removes an offset to the target."""
    limit = target_follow.MAX_CORRECTION_DEG_S
    return max(-limit, min(limit, offset_deg / target_follow.CORRECTION_S))


# Commands that do not end a follow.
FOLLOW_KEEPING_COMMANDS = (
    "follow_target",
    "reload_config",
    "set_step_size",
    "reduce_step_size",
    "increase_step_size",
)
# During a follow these commands correct the path, they do not move the mount.
FOLLOW_NUDGE_COMMANDS = ("manual_movement", "motion_start", "motion_stop")
# Sky direction (north, east) of the manual_movement directions.
SKY_DIRECTIONS = {
    "NORTH": (1.0, 0.0),
    "SOUTH": (-1.0, 0.0),
    "EAST": (0.0, 1.0),
    "WEST": (0.0, -1.0),
}
# The follow reads the trusted time again after this many seconds.
CLOCK_REFRESH_S = 30.0
# A mount position report older than this has no known time.
POSITION_MAX_AGE_S = 5.0
# The follow learns its pointing offset from a plate solve only while the
# mount moves slower than this relative to the stars (degrees per second),
# for at least the settle time. Then solve and mount position are of the
# same moment.
OFFSET_LEARN_MAX_DEG_S = 0.002
OFFSET_SETTLE_S = 1.0
OFFSET_CHECK_S = 1.0
# A larger offset is a wrong solve or a mount that needs a sync.
OFFSET_MAX_DEG = 5.0


def wrap180(angle: float) -> float:
    """Wrap an angle in degrees to [-180, +180)."""
    return (angle + 180.0) % 360.0 - 180.0


def local_sidereal_deg(dt: datetime.datetime, lon_deg: float) -> float:
    """The local apparent sidereal time in degrees."""
    t = calc_utils.sf_utils.ts.from_datetime(dt)
    return (float(t.gast) * 15.0 + lon_deg) % 360.0


def ra_rotation_room(
    hour_angle_deg: float, dec_deg: float, lat_deg: float
) -> tuple[float, float]:
    """How far the RA axis can turn east and west inside the limits, in
    degrees. East raises the RA and lowers the hour angle.

    The altitude at a fixed declination falls as the hour angle moves away
    from the meridian. So the lowest altitude of a turn is at one of its
    ends, and the altitude limit is a limit of the hour angle.
    """
    lat, dec = math.radians(lat_deg), math.radians(dec_deg)
    sin_min_alt = math.sin(math.radians(RA_ROTATION_MIN_ALT_DEG))
    max_ha = RA_ROTATION_MAX_HA_DEG
    across = math.cos(lat) * math.cos(dec)
    along = math.sin(lat) * math.sin(dec)
    if across < 1e-9:
        # At a pole the altitude does not change with the hour angle.
        if along < sin_min_alt:
            return 0.0, 0.0
    else:
        cos_ha = (sin_min_alt - along) / across
        if cos_ha > 1.0:
            return 0.0, 0.0
        if cos_ha > -1.0:
            max_ha = min(max_ha, math.degrees(math.acos(cos_ha)))
    off_meridian = abs(hour_angle_deg)
    if off_meridian > max_ha:
        return 0.0, 0.0
    away = max_ha - off_meridian
    toward = max(0.0, off_meridian - RA_ROTATION_MERIDIAN_MARGIN_DEG)
    # West of the meridian the hour angle is positive: east is toward it.
    if hour_angle_deg >= 0.0:
        return toward, away
    return away, toward


def plan_ra_rotation(
    hour_angle_deg: float,
    dec_deg: float,
    lat_deg: float,
    step_deg: float,
    count: int,
    min_step_deg: float,
) -> Optional[float]:
    """The signed angle of each of `count` RA rotations in one direction
    (positive is east), or None if no direction keeps the limits.

    The step is at most step_deg and smaller if the room needs that. If
    both directions keep the limits, the direction toward the meridian
    wins: the telescope points higher there.
    """
    east_room, west_room = ra_rotation_room(hour_angle_deg, dec_deg, lat_deg)
    toward_is_east = hour_angle_deg >= 0.0
    best: Optional[tuple[tuple[bool, float], float]] = None
    for sign, room in ((1.0, east_room), (-1.0, west_room)):
        step = min(step_deg, room / count - RA_ROTATION_OVERSHOOT_DEG)
        if step < min_step_deg:
            continue
        key = ((sign > 0) == toward_is_east, step)
        if best is None or key > best[0]:
            best = (key, sign * step)
    return None if best is None else best[1]


@dataclasses.dataclass
class RaRotation:
    """The running RA rotation."""

    start_ra: float
    # Positive is east (the RA rises).
    angle_deg: float
    # The phase before the rotation.
    previous: MountControlPhases
    # When the stop went out after the angle, or None while the mount turns.
    stopped_at: Optional[float] = None
    # The RA at the last change, and its time, for the wait until still.
    still_ra: float = 0.0
    still_since: float = 0.0


class MountControlBase:
    """
    Base class for mount control interfaces.

    This class defines the interface and shared logic for controlling a telescope mount.
    It is intended to be subclassed by specific mount implementations, which must override
    the abstract methods to provide hardware-specific functionality.

    Responsibilities of MountControlBase:
    - Manage shared state, communication queues, and logging for mount control.
    - Define the main control loop (`run`) and initialization sequence.
    - Provide abstract methods for mount initialization, movement, and position retrieval.

    Responsibilities of subclasses:
    - Implement hardware-specific logic of mount.
    - Handle communication with the actual mount hardware or protocol.
    - Call notification methods to inform the base class of mount state changes.

    Abstract methods to override in subclasses:
        init_mount(): Initialize the mount hardware and prepare for operation.
        sync_mount(current_position_radec): Synchronize the mount's pointing state.
        move_mount_to_target(target_position_radec): Move the mount to the specified target position.
        adjust_mount_drift_rates(drift_rate_adjustment_ra, drift_rate_adjustment_dec): Adjust the mount's drift rates.
        spiral_search(center_position_radec, max_radius_deg, step_size_deg): Perform a spiral search.
        move_mount_manual(direction, speed, duration): Move the mount manually in a specified direction and speed.

    Notification methods for subclasses to call:
        mount_current_position(current_mount_position_radec): Report current mount position.
        mount_target_reached(): Notify that the mount has reached the target.
        mount_stopped(): Notify that the mount has stopped moving.

    Methods to override:
        init(): Initialize the mount hardware and prepare for operation.
        disconnect(): Safely disconnect from the mount hardware.
        move_to_position(position): Move the mount to the specified position.
        get_current_position(): Retrieve the current position of the mount.
    Main loop:
        The `run` method manages the main control loop, calling `init` on startup and
        handling graceful shutdown on interruption.
    """

    # The directory where a follow stores corrected element sets.
    corrected_directory: Path = satellite_data_dir

    def __init__(
        self, mount_queue: Queue, console_queue: Queue, shared_state: SharedStateObj
    ):
        """
        Args:
            mount_queue: Queue for receiving target positions or commands.
            console_queue: Queue for sending messages to the user interface or console.
            shared_state: SharedStateObj for inter-process communication with other PiFinder components.

        Attributes:
            state: Current state of the mount (e.g., initialization, tracking).
        """
        self.mount_queue = mount_queue
        self.console_queue = console_queue
        self.shared_state = shared_state

        self.current_ra: Optional[float] = (
            None  # Mount current Right Ascension in degrees, or None
        )
        self.current_dec: Optional[float] = (
            None  # Mount current Declination in degrees, or None
        )

        self.target_ra: Optional[float] = (
            None  # Target Right Ascension in degrees, or None
        )
        self.target_dec: Optional[float] = (
            None  # Target Declination in degrees, or None
        )

        self.target_reached = (
            False  # Flag indicating if the target has been reached by th mount
        )

        self.step_size: float = 1.0  # Default step size for manual movements in degrees

        self.init_solve_ra: Optional[float] = None  # Solved RA for mount initialization
        self.init_solve_dec: Optional[float] = (
            None  # Solved Dec for mount initialization
        )

        self.state: MountControlPhases = MountControlPhases.MOUNT_INIT_TELESCOPE

        # The last fault, for the status (cleared by a good init).
        self._last_error = ""
        # When the running continuous move started, or None.
        self._motion_started: Optional[float] = None
        # The last status written to the shared state (publish_status).
        self._status_key: Optional[tuple] = None
        self._status_distance: Optional[float] = None
        self._status_written: float = 0.0

        # Drift compensation data structures
        self.drift_solve_times: list[float] = []  # Timestamps for each solve
        # RA values of the solves, unwrapped: each value is within 180° of
        # the first value of the window, so a window can cross RA 0.
        self.drift_solve_ra: list[float] = []
        self.drift_solve_dec: list[float] = []  # Dec_target values from solves
        # The shortest drift window in seconds. While no axis has a
        # significant drift, the window grows to DRIFT_WINDOW_MAX_S.
        self.drift_compensation_window: float = 10.0
        # The exposure time of the last solve of the last window.
        self._drift_used_until: Optional[float] = None

        # REFINE uses only a plate solve whose exposure ended this many
        # seconds after the mount reached the target, so the frame has no
        # slew blur.
        self.refine_settle_s: float = 1.0
        # REFINE waits this long for that solve.
        self.refine_solve_timeout_s: float = 15.0
        self._refine_after: float = 0.0
        # Sync-and-move rounds in REFINE before PiFinder stops refining.
        self.refine_max_iterations: int = 3
        self._refine_count: int = 0

        # System time of the last position report of the mount, 0 if none.
        self.current_time: float = 0.0
        # The moving target that the mount follows, or None.
        self._follow: Optional[TargetFollow] = None
        # The clock of the follow: unix time or None; tests replace it.
        self.clock: Callable[[], Optional[float]] = self._trusted_time
        self._clock_offset: Optional[float] = None
        self._clock_offset_time = 0.0
        # Pointing offset of the follow (RA, Dec degrees): plate solve minus
        # mount position.
        self._follow_offset: tuple[float, float] = (0.0, 0.0)
        self._follow_solve_time = 0.0
        self._follow_offset_check = 0.0
        # System time since which the mount moves slowly, or None.
        self._follow_quiet_since: Optional[float] = None
        # A held arrow during a follow: (north, east, last step, start).
        self._follow_motion: Optional[tuple[float, float, float, float]] = None
        # True while a follow keeps the tracking of the mount off.
        self._follow_tracking_off = False
        # The track rate: track_rates.SIDEREAL, LUNAR or SOLAR.
        self.track_rate: str = track_rates.SIDEREAL
        # The track rate of the running goto_target command.
        self._goto_track_rate: str = track_rates.SIDEREAL
        # When the mount sent its last position.
        self._last_position_time: float = 0.0
        # The running RA rotation, or None. Its timer is _motion_started.
        self._rotation: Optional[RaRotation] = None
        # The id and the result (ROTATION_*) of the last rotate_ra command.
        self._rotation_id: int = 0
        self._rotation_result: str = ""

    #
    # Methods to be overridden by subclasses for controlling the specifics of a mount
    #

    def init_mount(
        self,
        solve_ra_deg: Optional[float] = None,
        solve_dec_deg: Optional[float] = None,
    ) -> bool:
        """Initialize the mount, so that we receive updates and can send commands.

        The subclass needs to set up the mount and prepare it for operation.
        This may include connecting to the mount, setting initial parameters, un-parking, etc.

        Geographic coordinates and UTC time are now synced from SharedStateObj automatically,
        either during init_mount or via periodic_mount_task().

        If solve_ra_deg and solve_dec_deg are provided, the mount should sync to that position.

        The subclass needs to return a boolean indicating success or failure.
        A failure will cause the main loop to retry initialization after a delay.
        If the mount cannot be initialized, throw an exception to abort the process.
        This will be used to inform the user via the console queue.

        Args:
            solve_ra_deg: Solved Right Ascension in degrees for initial sync. Optional.
            solve_dec_deg: Solved Declination in degrees for initial sync. Optional.

        Returns:
            bool: True if initialization was successful, False otherwise.
        """
        raise NotImplementedError("This method should be overridden by subclasses.")

    def sync_mount(
        self, current_position_ra_deg: float, current_position_dec_deg: float
    ) -> bool:
        """Synchronize the mount's pointing state with the current position PiFinder is looking at.

        The subclass needs to return a boolean indicating success or failure.
        A failure will cause the main loop to retry synchronization after a delay.
        If the mount cannot be synchronized, throw an exception to abort the process.
        This will be used to inform the user via the console queue.

        Args:
            current_position_ra_deg: The current Right Ascension in degrees.
            current_position_dec_deg: The current Declination in degrees.
        Returns:
            bool: True if synchronization was successful, False otherwise.
        """
        raise NotImplementedError("This method should be overridden by subclasses.")

    def stop_mount(self) -> bool:
        """Stop any current movement of the mount.

        The subclass needs to return a boolean indicating success or failure,
        if the command was successfully sent.
        A failure will cause the main loop to retry stopping after a delay.
        If the mount cannot be stopped, throw an exception to abort the process.
        This will be used to inform the user via the console queue.

        You need to call the mount_stopped() method once the mount has actually stopped.

        Returns:
            bool: True if commanding a stop was successful, False otherwise.
        """
        raise NotImplementedError("This method should be overridden by subclasses.")

    def move_mount_to_target(self, target_ra_deg, target_dec_deg) -> bool:
        """Move the mount to the specified target position.

        The subclass needs to return a boolean indicating success or failure,
        if the command was successfully sent.
        A failure will cause the main loop to retry movement after a delay.
        If the mount cannot be moved, throw an exception to abort the process.
        This will be used to inform the user via the console queue.

        Args:
            target_ra_deg: The target right ascension in degrees.
            target_dec_deg: The target declination in degrees.

        Returns:
            bool: True if movement was successful, False otherwise.
        """
        raise NotImplementedError("This method should be overridden by subclasses.")

    def is_mount_moving(self) -> bool:
        """Check if the mount is currently moving.

        The subclass needs to return a boolean indicating whether the mount is moving or not.

        Returns:
            bool: True if the mount is moving, False otherwise.
        """
        raise NotImplementedError("This method should be overridden by subclasses.")

    def adjust_mount_drift_rates(
        self,
        delta_drift_rate_ra: float,
        delta_drift_rate_dec: float,
        ra_se: float = 0.0,
        dec_se: float = 0.0,
    ) -> bool:
        """Cancel a measured drift of the pointing.

        The parameters are the drift that the plate solves show: the RA and
        Dec of the pointing change at these rates. The mount changes its
        tracking so that this drift stops. The drift is measured while the
        earlier adjustments are in effect, so each call is an increment.
        An axis with a value of 0.0 has no significant drift.

        Args:
            delta_drift_rate_ra: RA drift of the pointing in degrees/second
            delta_drift_rate_dec: Dec drift of the pointing in degrees/second
            ra_se: standard error of the RA value (degrees/second)
            dec_se: standard error of the Dec value (degrees/second)

        The subclass needs to return a boolean indicating success or failure,
        if the command was successfully sent.
        A failure will cause the main loop to retry setting the rates after a delay.
        If the mount cannot adjust the drift rates, throw an exception to abort the process.
        This will be used to inform the user via the console queue.

        Returns:
            bool: True if adjusting drift rates was successful, False otherwise.
        """
        raise NotImplementedError("This method should be overridden by subclasses.")

    def set_track_rates(self, ra_rate_deg_s: float, dec_rate_deg_s: float) -> bool:
        """Track at these absolute rates of RA and Dec (JNow, degrees/second).

        Used to follow a moving target. A mount that cannot set custom rates
        returns False, and the follow uses repeated gotos.
        """
        return False

    def restore_sidereal_tracking(self) -> None:
        """Track at the sidereal rate again, after set_track_rates."""
        return None

    def set_tracking(self, on: bool) -> bool:
        """Turn the tracking of the mount on or off.

        Returns False if the mount cannot do it.
        """
        return False

    def apply_track_rate(self, rate: str) -> bool:
        """Track at the sidereal, lunar or solar rate (track_rates).

        Returns False if the mount cannot track at that rate.
        """
        return rate == track_rates.SIDEREAL

    def refresh_track_rate(self) -> None:
        """Called from the main loop. A mount that follows the Moon or the
        Sun with custom rates updates them here."""
        return None

    def move_mount_offset(
        self, north: float, east: float, step_size_deg: float
    ) -> bool:
        """Move by step_size_deg in the sky direction (north, east).
        Override in subclasses."""
        return False

    def start_motion(self, north: float, east: float, fastest: bool = False) -> bool:
        """Start moving in the sky direction (north, east) until
        stop_motion. Override in subclasses."""
        return False

    def stop_motion(self) -> bool:
        """Stop a continuous move. Override in subclasses."""
        return True

    def is_slewing(self) -> bool:
        """True while a goto runs. Override in subclasses."""
        return False

    def is_altaz(self) -> bool:
        """True when the mount reports that it is alt-az. Override in
        subclasses."""
        return False

    def _stop_motion(self) -> None:
        if self._rotation is not None:
            self._end_rotation(ROTATION_STOPPED)
            return
        if self._motion_started is not None:
            self._motion_started = None
            if not self.stop_motion():
                self.warn(_("Move not stopped!"))

    def check_motion_timeout(self, now: Optional[float] = None) -> None:
        """Stop a continuous move that runs longer than MAX_MOTION_S, and
        check a running RA rotation. The main loop calls this in every
        phase."""
        now = time.time() if now is None else now
        if self._rotation is not None:
            self._check_rotation(now)
            return
        if (
            self._motion_started is not None
            and now - self._motion_started > MAX_MOTION_S
        ):
            logger.warning("Continuous move ran %.0f s, stopping", MAX_MOTION_S)
            self._stop_motion()
            self.warn(_("Move stopped"))

    def _move_mount_offset(
        self, north: float, east: float, step_size_deg: float
    ) -> bool:
        success = self.move_mount_offset(north, east, step_size_deg)
        if success:
            self._manual_move_done()
        return success

    def _manual_move_done(self) -> None:
        """A manual move takes the mount off the target: the phase is
        TRACKING, and drift compensation stops."""
        if self.state == MountControlPhases.MOUNT_DRIFT_COMPENSATION:
            self._reset_drift_compensation_data()
        if self.state != MountControlPhases.MOUNT_TRACKING:
            logger.debug("Phase: -> MOUNT_TRACKING due to manual movement")
        self.state = MountControlPhases.MOUNT_TRACKING

    def move_mount_manual(
        self, direction: MountDirections, step_size_deg: float
    ) -> bool:
        """Move the mount manually in the specified direction by the specified step size.

        The subclass needs to return a boolean indicating success or failure,
        if the command was successfully sent.
        A failure will be reported back to the user.

        Args:
            direction: The direction to move see MountDirections and its subclasses.
            step_size_deg: Step size in degrees to move the mount.
        Returns:
            bool: True if manual movement command was successful, False otherwise.

        """
        raise NotImplementedError("This method should be overridden by subclasses.")

    def disconnect_mount(self) -> bool:
        """Safely disconnect from the mount hardware.

        The subclass needs to return a boolean indicating success or failure,
        if the command was successfully sent.
        A failure will cause the main loop to retry disconnection after a delay.
        If the mount cannot be disconnected, throw an exception to abort the process.
        This will be used to inform the user via the console queue.

        This should ideally stop any ongoing movements and release any resources, including the
        communication channel to the mount.

        Returns:
            bool: True if disconnection command was sent successfully, False otherwise.
        """
        raise NotImplementedError("This method should be overridden by subclasses.")

    #
    # Methods to be called by subclasses to inform the base class of mount state changes
    #

    def mount_current_position(self, ra_deg, dec_deg) -> None:
        """Receive the current position of the mount from subclasses.

        This method needs to be called by the subclass whenever it receives an update of the position from the mount.
        This will be used to update the target UI and show the current position to the user (i.e. update the arrow display).

        Args:
            ra_deg: Current Right Ascension in degrees.
            dec_deg: Current Declination in degrees.

        """
        logger.debug(f"Mount current position: RA={ra_deg:.4f}°, Dec={dec_deg:.4f}°")
        self.current_ra = ra_deg
        self.current_dec = dec_deg
        self._last_position_time = time.time()

    def mount_target_reached(self) -> None:
        """Notification that the mount has reached the target position and stopped slewing.

        This method needs to be called by the subclass whenever it detects that the mount has reached the target position.
        This will be used to transition to the next phase in the control loop.

        """
        logger.debug(f"Mount target reached {self.state}")
        self.target_reached = True

    def mount_stopped(self) -> None:
        """Notification that the mount has stopped.

        This method needs to be called by the subclass whenever it detects that the mount has stopped and is not moving anymore.
        Even if it has not reached the target position. The mount must not be tracking, too.

        This will be used to transition to the MOUNT_STOPPED phase in the control loop, regardless of the previous phase.
        """
        logger.debug("Phase: -> MOUNT_STOPPED")
        self._follow = None
        self.state = MountControlPhases.MOUNT_STOPPED

    #
    # Helper methods for drift compensation
    #
    def _compute_linear_fit(
        self, x_values: list[float], y_values: list[float]
    ) -> tuple[float, float, float]:
        """Fit a straight line by least squares.

        Args:
            x_values: List of independent variable values (time).
            y_values: List of dependent variable values (RA or Dec).

        Returns:
            Tuple of (slope, intercept, slope_se). slope_se is the standard
            error of the slope from the residuals of the fit. It is
            infinite with fewer than three values.
        """
        n = len(x_values)
        if n < 3:
            return 0.0, 0.0, math.inf

        x_mean = sum(x_values) / n
        y_mean = sum(y_values) / n
        sxx = sum((x - x_mean) ** 2 for x in x_values)
        if sxx == 0:
            return 0.0, y_mean, math.inf
        sxy = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
        slope = sxy / sxx
        intercept = y_mean - slope * x_mean

        ss_res = sum(
            (y - (slope * x + intercept)) ** 2 for x, y in zip(x_values, y_values)
        )
        slope_se = math.sqrt(ss_res / (n - 2) / sxx)
        return slope, intercept, slope_se

    def _drift_correction(
        self, slope: float, slope_se: float, sky_scale: float
    ) -> tuple[float, float]:
        """The correction for one axis and its standard error.

        An axis gets a correction only if its slope is significant and its
        drift on the sky (slope times sky_scale) is above the floor. Else
        the correction is (0.0, 0.0).
        """
        if abs(slope) < DRIFT_SIGNIFICANCE_SE * slope_se:
            return 0.0, 0.0
        if abs(slope) * sky_scale < DRIFT_MIN_CORRECTION_DEG_S:
            return 0.0, 0.0
        return DRIFT_CORRECTION_GAIN * slope, DRIFT_CORRECTION_GAIN * slope_se

    def _reset_drift_compensation_data(self) -> None:
        """Reset drift compensation data collection and clear current drift rates."""
        self.drift_solve_times.clear()
        self.drift_solve_ra.clear()
        self.drift_solve_dec.clear()
        self.drift_rates_applied = False

    def _start_drift_window(self) -> None:
        """Clear the drift data for a new window. The new window uses only
        solves after the last solve of the old window."""
        if self.drift_solve_times:
            self._drift_used_until = self.drift_solve_times[-1]
        self._reset_drift_compensation_data()

    #
    # Helper methods to decorate mount control methods with state management
    #
    def status_text(self) -> str:
        """The short phase text of the status line."""
        texts = {
            MountControlPhases.MOUNT_UNKNOWN: _("Not connected"),
            MountControlPhases.MOUNT_INIT_TELESCOPE: _("Connecting"),
            MountControlPhases.MOUNT_TRACKING: _("Tracking"),
            MountControlPhases.MOUNT_STOPPED: _("Stopped"),
            MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE: _("Slewing"),
            MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE: _("Refining"),
            MountControlPhases.MOUNT_DRIFT_COMPENSATION: _("On target"),
            MountControlPhases.MOUNT_SPIRAL_SEARCH: _("Searching"),
            MountControlPhases.MOUNT_RA_ROTATION: _("Turning RA"),
        }
        if self._motion_started is not None and self._rotation is None:
            return _("Moving")
        if self.state == MountControlPhases.MOUNT_TARGET_FOLLOW and self._follow:
            return self._follow_status_text()
        text = texts.get(self.state, str(self.state.name))
        if self.track_rate != track_rates.SIDEREAL and self.state in (
            MountControlPhases.MOUNT_TRACKING,
            MountControlPhases.MOUNT_DRIFT_COMPENSATION,
        ):
            text = f"{text} {track_rate_label(self.track_rate)}"
        if self.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE:
            text = f"{text} {self._refine_count + 1}/{self.refine_max_iterations}"
        return text

    def status_model(self) -> str:
        """The mount model for the status. Override in subclasses."""
        return ""

    def mount_status(self, now: Optional[float] = None) -> MountStatus:
        distance = None
        if (
            self.target_ra is not None
            and self.target_dec is not None
            and self.current_ra is not None
            and self.current_dec is not None
        ):
            distance = angular_distance(
                self.current_ra, self.current_dec, self.target_ra, self.target_dec
            )
        return MountStatus(
            phase=self.state.name,
            text=self.status_text(),
            distance_deg=distance,
            step_deg=self.step_size,
            model=self.status_model(),
            updated=time.time() if now is None else now,
            error=self._last_error,
            ra_deg=self.current_ra,
            dec_deg=self.current_dec,
            rotation_id=self._rotation_id,
            rotation=(
                ROTATION_TURNING
                if self._rotation is not None
                else self._rotation_result
            ),
            altaz=self.is_altaz(),
        )

    def publish_status(self) -> None:
        """Write the status to the shared state when it changed (see
        STATUS_DISTANCE_PERIOD_S and STATUS_HEARTBEAT_S)."""
        now = time.time()
        status = self.mount_status(now)
        key = (
            status.phase,
            status.text,
            status.step_deg,
            status.model,
            status.error,
            status.rotation_id,
            status.rotation,
            status.altaz,
        )
        age = now - self._status_written
        distance_changed = status.distance_deg != self._status_distance
        if (
            key == self._status_key
            and not (distance_changed and age >= STATUS_DISTANCE_PERIOD_S)
            and age < STATUS_HEARTBEAT_S
        ):
            return
        self.shared_state.set_mount_status(status)
        self._status_key = key
        self._status_distance = status.distance_deg
        self._status_written = now

    def warn(self, text: str) -> None:
        """Show a fault on the screen and keep it for the status."""
        self._last_error = text
        self.console_queue.put(["WARNING", text])

    def notify(self, text: str) -> None:
        """Show mount control progress on the PiFinder screen."""
        self.console_queue.put(["MOUNT", text])

    def _stop_mount(self) -> bool:
        if self.state != MountControlPhases.MOUNT_STOPPED:
            # Reset drift compensation data when stopping
            if self.state == MountControlPhases.MOUNT_DRIFT_COMPENSATION:
                self._reset_drift_compensation_data()
            # State is set in mount_stopped() callback
            stopped = self.stop_mount()
            if stopped:
                self.notify(_("Mount stopped"))
            return stopped
        else:
            logger.debug("Mount already stopped, not sending stop command")
            return True

    def _move_mount_manual(
        self, direction: MountDirections, step_size_deg: float
    ) -> bool:
        """Convert string direction to enum and move mount manually."""
        # Convert string to enum if needed (case-insensitive)
        if isinstance(direction, str):
            direction_upper = direction.upper()
            # Try equatorial directions first
            try:
                if direction_upper == "NORTH":
                    direction = MountDirectionsEquatorial.NORTH
                elif direction_upper == "SOUTH":
                    direction = MountDirectionsEquatorial.SOUTH
                elif direction_upper == "EAST":
                    direction = MountDirectionsEquatorial.EAST
                elif direction_upper == "WEST":
                    direction = MountDirectionsEquatorial.WEST
                # Try alt-az directions
                elif direction_upper == "UP":
                    direction = MountDirectionsAltAz.UP
                elif direction_upper == "DOWN":
                    direction = MountDirectionsAltAz.DOWN
                elif direction_upper == "LEFT":
                    direction = MountDirectionsAltAz.LEFT
                elif direction_upper == "RIGHT":
                    direction = MountDirectionsAltAz.RIGHT
                else:
                    logger.warning(f"Unknown direction string: {direction}")
                    return False
            except Exception as e:
                logger.warning(f"Failed to convert direction string '{direction}': {e}")
                return False

        success = self.move_mount_manual(direction, step_size_deg)
        if success:
            self._manual_move_done()
            names = {
                MountDirectionsEquatorial.NORTH: _("North"),
                MountDirectionsEquatorial.SOUTH: _("South"),
                MountDirectionsEquatorial.EAST: _("East"),
                MountDirectionsEquatorial.WEST: _("West"),
                MountDirectionsAltAz.UP: _("Up"),
                MountDirectionsAltAz.DOWN: _("Down"),
                MountDirectionsAltAz.LEFT: _("Left"),
                MountDirectionsAltAz.RIGHT: _("Right"),
            }
            self.notify(f"{names.get(direction, '')} {format_step(step_size_deg)}")
        return success

    def _goto_target(self, target_ra, target_dec) -> bool:
        success = self.move_mount_to_target(target_ra, target_dec)
        if success:
            self._set_track_rate(self._goto_track_rate)
            # Reset drift compensation when starting a new target acquisition
            if self.state == MountControlPhases.MOUNT_DRIFT_COMPENSATION:
                self._reset_drift_compensation_data()
            self.target_reached = False
            self._refine_count = 0
            self.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE
            logger.debug(
                f"Phase: -> MOUNT_TARGET_ACQUISITION_MOVE to RA={target_ra}, DEC={target_dec}"
            )
            self.notify(_("Slewing"))
        return success

    def _set_track_rate(self, rate: str) -> None:
        if rate not in track_rates.TRACK_RATES:
            logger.warning("Unknown track rate %s", rate)
            rate = track_rates.SIDEREAL
        if rate == self.track_rate and rate == track_rates.SIDEREAL:
            return
        if self.apply_track_rate(rate):
            if rate != self.track_rate and rate != track_rates.SIDEREAL:
                self.notify(_("Track rate") + " " + track_rate_label(rate))
            self.track_rate = rate
            return
        self.warn(_("No such track rate"))
        if self.apply_track_rate(track_rates.SIDEREAL):
            self.track_rate = track_rates.SIDEREAL

    #
    # Follow of a moving target
    #

    def _trusted_time(self) -> Optional[float]:
        """Unix time from the time of PiFinder (GPS), or None without it.

        The system clock of a PiFinder without a network can be wrong by
        seconds or more, and a satellite moves a degree in one second.
        """
        now = time.time()
        if (
            self._clock_offset is None
            or now - self._clock_offset_time > CLOCK_REFRESH_S
        ):
            dt = self.shared_state.datetime()
            if dt is not None:
                self._clock_offset = dt.timestamp() - now
                self._clock_offset_time = now
        return None if self._clock_offset is None else now + self._clock_offset

    def _start_follow(self, command: dict) -> None:
        location = self.shared_state.location()
        if location is None or not location.lock:
            self.warn(_("No location"))
            return
        self._clock_offset = None
        now = self.clock()
        if now is None:
            self.warn(_("No time"))
            return
        try:
            target = target_follow.target_from_command(command, location)
            follow = TargetFollow(target, now)
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Bad follow_target command: %s", exc)
            self.warn(_("Bad target data"))
            return
        if follow.point(now).alt < target_follow.MIN_ALT_DEG:
            self.warn(_("Target too low"))
            return
        self._follow = follow
        self._follow_offset = (0.0, 0.0)
        self._follow_solve_time = time.time()
        self._follow_motion = None
        self.track_rate = track_rates.SIDEREAL
        self._reset_drift_compensation_data()
        logger.info("Following %s", follow.name)
        self.notify(_("Follow") + " " + follow.name)
        self._follow_aim(now)

    def _follow_aim(self, now: float) -> None:
        """Goto the target, ahead of it if it is fast."""
        follow = self._follow
        if follow is None:
            return
        self.restore_sidereal_tracking()
        self._follow_quiet_since = None
        target = follow.aim(now)
        self.target_ra, self.target_dec = target.ra, target.dec
        self.target_reached = False
        d_ra, d_dec = self._follow_offset
        if self.move_mount_to_target((target.ra - d_ra) % 360.0, target.dec - d_dec):
            self.state = MountControlPhases.MOUNT_TARGET_FOLLOW
            logger.debug(
                "Follow: aim %d, lead %.0f s, RA=%.3f Dec=%.3f",
                follow.aim_count,
                follow.lead_s,
                target.ra,
                target.dec,
            )
        else:
            self.warn(_("Goto failed!"))
            self._end_follow()

    def _end_follow(self) -> None:
        follow = self._follow
        if follow is None:
            return
        logger.info("Follow of %s ends", follow.name)
        elements = follow.corrected_elements()
        if elements is not None:
            self._save_corrected(follow, elements)
        self._follow = None
        self._follow_motion = None
        if self._follow_tracking_off:
            self._follow_tracking_off = False
            self.set_tracking(True)
        self.restore_sidereal_tracking()
        if self.state == MountControlPhases.MOUNT_TARGET_FOLLOW:
            self.state = MountControlPhases.MOUNT_TRACKING

    def _save_corrected(
        self, follow: TargetFollow, elements: satellites.SatElements
    ) -> None:
        """Store the elements with the correction of the user. The catalog
        uses them for the next follow and the next passes."""
        now = self.clock()
        if now is None:
            now = time.time()
        when = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
        logger.info(
            "Follow: %s was %+.1f s ahead of its elements. Corrected:\n%s",
            follow.name,
            follow.time_offset_s,
            elements.to_tle(),
        )
        try:
            saved = satellites.save_corrected_element(
                elements, when, self.corrected_directory
            )
        except OSError as exc:
            logger.warning("Cannot store the corrected elements: %s", exc)
            return
        self.notify(_("Saved") + " " + saved.name)

    def _follow_pointing(self) -> Optional[tuple[float, float]]:
        """Where the telescope points: the mount position plus the offset
        from the last plate solve. None without a mount position."""
        if self.current_ra is None or self.current_dec is None:
            return None
        d_ra, d_dec = self._follow_offset
        return (self.current_ra + d_ra) % 360.0, self.current_dec + d_dec

    def _position_time(self, now: float) -> float:
        """The follow time of the last mount position report."""
        if not self.current_time:
            return now
        age = time.time() - self.current_time
        return now - age if 0.0 <= age <= POSITION_MAX_AGE_S else now

    def _learn_follow_offset(self) -> None:
        """Take the pointing offset from a new plate solve.

        A solve works before a pass, while the mount waits at the aim point,
        and during the follow of a slow target. During a fast pass the stars
        are streaks and no solve arrives: the last offset stays.
        """
        quiet_since = self._follow_quiet_since
        system_now = time.time()
        if quiet_since is None or self.current_ra is None or self.current_dec is None:
            return
        if system_now - self._follow_offset_check < OFFSET_CHECK_S:
            return
        self._follow_offset_check = system_now
        latest = self.latest_solve()
        if latest is None:
            return
        ra, dec, solved = latest
        if solved <= self._follow_solve_time or solved < quiet_since + OFFSET_SETTLE_S:
            return
        self._follow_solve_time = solved
        offset = (
            target_follow.wrap_degrees(ra - self.current_ra),
            dec - self.current_dec,
        )
        if max(abs(offset[0]), abs(offset[1])) > OFFSET_MAX_DEG:
            logger.warning("Follow: solve is %.1f°, %.1f° from the mount", *offset)
            return
        self._follow_offset = offset
        logger.debug("Follow: pointing offset RA %+.3f° Dec %+.3f°", *offset)

    def _follow_set_rates(self, ra_rate: float, dec_rate: float) -> bool:
        """Set the track rates and note if the mount now moves slowly."""
        if not self.set_track_rates(ra_rate, dec_rate):
            return False
        if math.hypot(ra_rate, dec_rate) > OFFSET_LEARN_MAX_DEG_S:
            self._follow_quiet_since = None
        elif self._follow_quiet_since is None:
            self._follow_quiet_since = time.time()
        return True

    def _follow_pass(self, point: target_follow.FollowPoint) -> None:
        """Follow with gotos, for a mount without custom rates.

        A target that is almost fixed in alt-az, as a geostationary
        satellite, stays in view with tracking off. Then a goto is necessary
        only for its small motion.
        """
        follow = self._follow
        if follow is None:
            return
        follow.stage = FollowStage.PASS
        if (
            not self._follow_tracking_off
            and target_follow.ground_fixed(point)
            and self.set_tracking(False)
        ):
            self._follow_tracking_off = True
            logger.info("Follow: %s is fixed in alt-az, tracking off", follow.name)

    def _follow_step(self, now: Optional[float]) -> None:
        """One step of the follow, from the phase loop (10 times a second)."""
        follow = self._follow
        if follow is None:
            self.state = MountControlPhases.MOUNT_TRACKING
            return
        if now is None:
            self.warn(_("No time"))
            self._end_follow()
            return
        self._follow_held_arrow(follow, now)
        point = follow.point(now)
        if point.alt < target_follow.MIN_ALT_DEG:
            self.notify(follow.name + " " + _("set"))
            self._end_follow()
            self._stop_mount()
            return
        self._learn_follow_offset()

        if follow.stage == FollowStage.AIM:
            if self.target_reached or not self.is_mount_moving():
                self.target_reached = False
                follow.slew_done(now)
                self._follow_quiet_since = time.time()
                if (
                    follow.late(now)
                    and follow.aim_ra is not None
                    and follow.aim_dec is not None
                    and angular_distance(
                        point.ra, point.dec, follow.aim_ra, follow.aim_dec
                    )
                    > target_follow.TRACK_MAX_ERROR_DEG
                ):
                    # The slew took longer than the lead and the target is
                    # far past: aim again with the measured slew time.
                    self._follow_aim(now)
            return

        if follow.stage == FollowStage.WAIT:
            if not follow.arrived(now):
                return
            if self._follow_set_rates(point.ra_rate, point.dec_rate):
                follow.stage = FollowStage.TRACK
                follow.last_rate_update = now
            else:
                self._follow_pass(point)
            return

        self.target_ra, self.target_dec = point.ra, point.dec
        pointing = self._follow_pointing()
        if follow.stage == FollowStage.TRACK:
            if not follow.rate_update_due(now):
                return
            ra_rate, dec_rate = point.ra_rate, point.dec_rate
            if pointing is not None:
                # The target at the time of the mount position report, so
                # the delay of the report causes no error.
                at = follow.point(self._position_time(now))
                d_ra = target_follow.wrap_degrees(at.ra - pointing[0])
                d_dec = at.dec - pointing[1]
                error = angular_distance(at.ra, at.dec, *pointing)
                if error > target_follow.TRACK_MAX_ERROR_DEG:
                    logger.info("Follow: %.2f° off, aim again", error)
                    self._follow_aim(now)
                    return
                ra_rate += _follow_correction(d_ra)
                dec_rate += _follow_correction(d_dec)
            if not self._follow_set_rates(ra_rate, dec_rate):
                self._follow_pass(point)
            return

        if follow.stage == FollowStage.PASS and follow.arrived(now):
            if pointing is None and follow.aim_ra is not None:
                pointing = (follow.aim_ra, follow.aim_dec or 0.0)
            if pointing is None or angular_distance(
                point.ra, point.dec, *pointing
            ) > follow.pass_distance(point):
                self._follow_aim(now)

    def _follow_nudge_command(self, command: dict, now: Optional[float]) -> None:
        """An arrow during a follow moves the path, not only the mount: the
        follow then holds the target where the user put it."""
        follow = self._follow
        if follow is None or now is None:
            return
        if command["type"] == "motion_stop":
            self._follow_motion = None
            return
        if "offset" in command:
            north, east = command["offset"]
        elif "north" in command:
            north, east = command["north"], command["east"]
        else:
            direction = str(command.get("direction", "")).upper()
            if direction not in SKY_DIRECTIONS:
                self.warn(_("Mount did not move!"))
                return
            north, east = SKY_DIRECTIONS[direction]
        if command["type"] == "motion_start":
            self._follow_motion = (north, east, now, now)
            return
        step_size = command.get("step_size", self.step_size)
        follow.nudge(north * step_size, east * step_size, now)
        self._follow_nudged(follow)
        label = command.get("label", "")
        self.notify(f"{label} {format_step(step_size)}".strip())

    def _follow_held_arrow(self, follow: TargetFollow, now: float) -> None:
        """A held arrow moves the path one step size per second."""
        if self._follow_motion is None:
            return
        north, east, last, started = self._follow_motion
        if now - started > MAX_MOTION_S:
            self._follow_motion = None
            return
        angle = self.step_size * (now - last)
        follow.nudge(north * angle, east * angle, now)
        self._follow_motion = (north, east, now, started)

    def _follow_nudged(self, follow: TargetFollow) -> None:
        # The mount moves to the new path at the next rate update.
        follow.last_rate_update = 0.0
        logger.debug(
            "Follow: correction %+.1f s, across %+.3f°, N %+.3f° E %+.3f°",
            follow.time_offset_s,
            follow.cross_deg,
            follow.offset_north,
            follow.offset_east,
        )

    def _follow_status_text(self) -> str:
        follow = self._follow
        if follow is None:
            return ""
        if follow.stage == FollowStage.AIM:
            return _("Follow: slewing")
        correction = ""
        if abs(follow.time_offset_s) >= target_follow.MIN_TIME_OFFSET_S:
            correction = f" {follow.time_offset_s:+.1f}s"
        if follow.stage == FollowStage.WAIT:
            now = self.clock()
            seconds = 0.0 if now is None else follow.seconds_to_arrival(now)
            return _("Follow: in") + f" {seconds:.0f}s" + correction
        if follow.stage == FollowStage.TRACK:
            return _("Following") + correction
        return _("Follow: passing") + correction

    #
    # RA rotation for the polar alignment
    #

    def _hour_angle(self) -> Optional[float]:
        """The hour angle of the mount position in degrees, or None
        without the time, a located site or a mount position."""
        dt = self.shared_state.datetime()
        location = self.shared_state.location()
        if dt is None or location is None or not location.lock:
            return None
        if self.current_ra is None:
            return None
        return wrap180(local_sidereal_deg(dt, location.lon) - self.current_ra)

    def _rotation_fault(self, angle_deg: float) -> str:
        """Why the mount must not turn its RA axis by the signed angle, or
        an empty text if it can."""
        if self.is_altaz():
            return _("Not equatorial")
        if self.state in (
            MountControlPhases.MOUNT_UNKNOWN,
            MountControlPhases.MOUNT_INIT_TELESCOPE,
        ):
            return _("Mount not ready")
        if (
            self.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE
            or self.is_slewing()
        ):
            return _("Mount is slewing")
        if self.current_ra is None or self.current_dec is None:
            return _("No mount position")
        hour_angle = self._hour_angle()
        if hour_angle is None:
            return _("Need GPS lock")
        east_room, west_room = ra_rotation_room(
            hour_angle, self.current_dec, self.shared_state.location().lat
        )
        room = east_room if angle_deg > 0 else west_room
        if room < abs(angle_deg) + RA_ROTATION_OVERSHOOT_DEG:
            return _("RA turn not safe")
        return ""

    def _start_rotation(self, angle_deg: float, rotation_id: int = 0) -> None:
        """Turn the RA axis by the signed angle (positive is east). The
        sender chooses the direction; the limits are checked here."""
        self._rotation_id = rotation_id
        self._rotation_result = ROTATION_REFUSED
        size = max(RA_ROTATION_MIN_DEG, min(RA_ROTATION_MAX_DEG, abs(angle_deg)))
        angle_deg = size if angle_deg > 0 else -size
        fault = self._rotation_fault(angle_deg)
        if fault:
            logger.warning("RA rotation %+.1f° refused: %s", angle_deg, fault)
            self.warn(fault)
            return
        assert self.current_ra is not None
        if not self.start_motion(0.0, 1.0 if angle_deg > 0 else -1.0, fastest=True):
            self._rotation_result = ROTATION_FAILED
            self.warn(_("Mount did not move!"))
            return
        self._motion_started = time.time()
        self._rotation = RaRotation(self.current_ra, angle_deg, self.state)
        self._reset_drift_compensation_data()
        self.state = MountControlPhases.MOUNT_RA_ROTATION
        logger.info("RA rotation %+.1f° (positive is east)", angle_deg)

    def _end_rotation(self, result: str) -> None:
        """End the rotation with a result. Stop the motion if it still
        runs. The phase returns to the one before the rotation."""
        rotation = self._rotation
        if rotation is None:
            return
        self._rotation = None
        self._rotation_result = result
        self._motion_started = None
        if rotation.stopped_at is None and not self.stop_motion():
            # The last option: abort all motion of the mount.
            self.warn(_("Move not stopped!"))
            self.stop_mount()
        if self.state == MountControlPhases.MOUNT_RA_ROTATION:
            # The rotation took the mount off a goto target, so drift
            # compensation and refine do not continue.
            if rotation.previous == MountControlPhases.MOUNT_STOPPED:
                self.state = MountControlPhases.MOUNT_STOPPED
            else:
                self.state = MountControlPhases.MOUNT_TRACKING
        logger.info("RA rotation ended: %s", result)

    def _check_rotation(self, now: float) -> None:
        """Stop the rotation at the angle, on a fault, or when the phase
        changed. Then wait until the mount is still. This does not depend
        on the phase."""
        rotation = self._rotation
        if rotation is None:
            return
        if self.state != MountControlPhases.MOUNT_RA_ROTATION:
            logger.warning("Phase %s during the RA rotation", self.state.name)
            self._end_rotation(ROTATION_STOPPED)
            return
        if self.current_ra is None:
            self._end_rotation(ROTATION_STALE)
            self.warn(_("No mount position"))
            return
        if rotation.stopped_at is not None:
            if abs(wrap180(self.current_ra - rotation.still_ra)) > (
                RA_ROTATION_STILL_DEG
            ):
                rotation.still_ra = self.current_ra
                rotation.still_since = now
            if now - rotation.still_since >= RA_ROTATION_STILL_S:
                self._end_rotation(ROTATION_DONE)
            elif now - rotation.stopped_at > RA_ROTATION_STILL_TIMEOUT_S:
                logger.warning("The mount still moves after the stop")
                self._end_rotation(ROTATION_TIMEOUT)
                self.warn(_("Mount not still"))
                self.stop_mount()
            return
        started = now if self._motion_started is None else self._motion_started
        direction = 1.0 if rotation.angle_deg > 0 else -1.0
        turned = direction * wrap180(self.current_ra - rotation.start_ra)
        if turned >= abs(rotation.angle_deg):
            logger.info("RA rotation reached %.1f°", turned)
            self._motion_started = None
            rotation.stopped_at = now
            rotation.still_ra = self.current_ra
            rotation.still_since = now
            if not self.stop_motion():
                self._end_rotation(ROTATION_FAILED)
                self.warn(_("Move not stopped!"))
                self.stop_mount()
        elif turned <= -RA_ROTATION_WRONG_WAY_DEG:
            logger.warning("RA rotation went the wrong way: %.1f°", turned)
            self._end_rotation(ROTATION_FAILED)
            self.warn(_("Wrong RA direction"))
        elif now - max(self._last_position_time, started) > RA_ROTATION_STALE_S:
            logger.warning("No mount position during the RA rotation")
            self._end_rotation(ROTATION_STALE)
            self.warn(_("No mount position"))
        elif now - started > RA_ROTATION_TIMEOUT_S:
            logger.warning("RA rotation stopped after %.0f s", now - started)
            self._end_rotation(ROTATION_TIMEOUT)
            self.warn(_("Rotation too slow"))

    #
    # Shared logic and main loop
    #

    def set_mount_step_size(self, step_size_deg: float) -> bool:
        """Set the mount's step size for manual movements.

        The subclass needs to return a boolean indicating success or failure,
        if the command was successfully sent.
        A failure will be reported back to the user.

        Args:
            step_size_deg: The new step size to set (degrees)

        Returns:
            bool: True if setting step size was successful, False otherwise.
        """
        self.step_size = step_size_deg
        return True

    def get_mount_step_size(self) -> float:
        """Get the current mount's step size for manual movements.

        Returns:
            float: The current step size (degrees).
        """
        return self.step_size

    def spiral_search(
        self, center_position_radec, max_radius_deg, step_size_deg
    ) -> None:
        """Commands the mount to perform a spiral search around the center position."""
        raise NotImplementedError("Not yet implemented.")

    def reload_settings(self) -> None:
        """Apply changed settings. Override in subclasses that have any."""
        pass

    def latest_solve(self) -> Optional[tuple[float, float, float]]:
        """The last plate solve of the aligned axis, in JNow degrees.

        Returns (ra_deg, dec_deg, exposure_end) or None. Only a camera solve
        counts, never an IMU estimate. Mounts use the coordinates of date,
        so the J2000 solve is converted with the current datetime.
        """
        solution = self.shared_state.solution()
        if solution is None or solution.last_solve_success is None:
            return None
        solve = solution.pointing.aligned.solve
        if solve is None:
            return None
        dt = self.shared_state.datetime()
        if dt is None:
            return None
        ra, dec = calc_utils.j2000_to_jnow(solve.RA, solve.Dec, dt)
        return ra, dec, solution.last_solve_success

    def periodic_mount_task(self) -> None:
        """Periodic task called every 5 seconds from the main loop.

        Override in subclasses to add periodic tasks (e.g., syncing location/time).
        Default implementation does nothing.
        """
        pass

    def _process_command(
        self, command, retry_count: int = 3, delay: float = 2.0
    ) -> Generator:
        """Process a command received from the mount queue.
        This is a generator function that yields control back to the main loop to allow for mount state processing and retries.
        This function does not call mount control methods directly, but calls internal helper functions that in addition manage state.
        The only exception is when retrying failed and we need to change the state to MOUNT_INIT_TELESCOPE or MOUNT_STOPPED.
        """

        # Any other command ends a continuous move first. Every command
        # ends an RA rotation.
        if command["type"] not in ("motion_start", "motion_stop"):
            self._stop_motion()
        if self._follow is not None and command["type"] in FOLLOW_NUDGE_COMMANDS:
            self._follow_nudge_command(command, self.clock())
            return
        # A command that moves the mount, or stops it, ends a follow.
        if command["type"] not in FOLLOW_KEEPING_COMMANDS:
            self._end_follow()

        # Process the command based on its type
        if command["type"] == "motion_start":
            self._stop_motion()
            if self.start_motion(command["north"], command["east"]):
                self._motion_started = time.time()
                self._manual_move_done()
            else:
                self.warn(_("Mount did not move!"))

        elif command["type"] == "motion_stop":
            self._stop_motion()

        elif command["type"] == "exit":
            # This is here for debugging and testing purposes.
            logger.warning("Mount control exiting on command.")
            self._stop_mount()
            sys.exit(0)
            # raise KeyboardInterrupt("Mount control exiting on command.")

        elif command["type"] == "stop_movement":
            logger.debug("Mount: stop command received")
            while retry_count > 0 and not self._stop_mount():
                # Wait for delay before retrying
                start_time = time.time()
                while time.time() - start_time <= delay:
                    yield
                retry_count -= 1
                if retry_count == 0:
                    logger.error(
                        "Failed to stop mount after retrying. Re-initializing mount."
                    )
                    self.warn(_("Cannot stop mount!"))
                    self.state = MountControlPhases.MOUNT_INIT_TELESCOPE
                else:
                    logger.warning(
                        "Retrying to stop mount. Attempts left: %d", retry_count
                    )
                    yield

        elif command["type"] == "sync":
            logger.debug("Mount: sync command received")
            if "ra" in command:
                sync_ra = command["ra"]
                sync_dec = command["dec"]
            else:
                # Sync to the last plate solve.
                latest = self.latest_solve()
                if latest is None:
                    self.warn(_("No solve"))
                    return
                sync_ra, sync_dec, _solve_time = latest
            logger.debug(f"Mount: Syncing - RA={sync_ra}, DEC={sync_dec}")
            while retry_count > 0 and not self.sync_mount(sync_ra, sync_dec):
                # Wait for delay before retrying
                start_time = time.time()
                while time.time() - start_time <= delay:
                    yield
                retry_count -= 1
                if retry_count == 0:
                    logger.error(
                        "Failed to sync mount after retrying. Re-initializing."
                    )
                    self.warn(_("Cannot sync mount!"))
                    self.state = MountControlPhases.MOUNT_INIT_TELESCOPE
                else:
                    logger.warning(
                        "Retrying to sync mount. Attempts left: %d", retry_count
                    )
                    yield
            if retry_count > 0:
                self.notify(_("Mount synced"))

        elif command["type"] == "follow_target":
            self._start_follow(command)

        elif command["type"] == "set_track_rate":
            self._set_track_rate(command.get("rate", track_rates.SIDEREAL))
        elif command["type"] == "rotate_ra":
            self._start_rotation(float(command["angle_deg"]), int(command.get("id", 0)))
        elif command["type"] == "goto_target":
            logger.debug("Mount: goto_target command received")
            self._goto_track_rate = command.get("track_rate", track_rates.SIDEREAL)
            self.target_ra = command["ra"]
            self.target_dec = command["dec"]
            if command.get("epoch") == "J2000":
                # Catalog coordinates: the mount uses coordinates of date.
                dt = self.shared_state.datetime()
                if dt is None:
                    self.warn(_("No time"))
                    return
                self.target_ra, self.target_dec = calc_utils.j2000_to_jnow(
                    command["ra"], command["dec"], dt
                )
            logger.debug(
                f"Mount: Goto target - RA={self.target_ra}, DEC={self.target_dec}"
            )
            retry_stop = retry_count  # store for later waits
            while retry_count > 0 and not self._goto_target(
                self.target_ra, self.target_dec
            ):
                # Wait for delay before retrying
                start_time = time.time()
                while time.time() - start_time <= delay:
                    yield
                retry_count -= 1
                if retry_count == 0:
                    logger.error("Failed to command mount to move to target.")
                    self.warn(_("Goto failed!"))
                    # Try to stop the mount.
                    logger.warning(
                        f"Stopping mount after failed goto_target. {retry_stop} retries"
                    )
                    stop_mount_cmd = self._process_command(
                        {"type": "stop_movement"}, retry_stop, delay
                    )
                    yield from stop_mount_cmd
                else:
                    logger.warning(
                        "Retrying to move mount to target. Attempts left: %d",
                        retry_count,
                    )
                    yield

        elif command["type"] == "manual_movement" and "offset" in command:
            # A move in any sky direction: (north, east) parts of a unit
            # vector, from the eyepiece view. "label" names it on screen.
            north, east = command["offset"]
            step_size = command.get("step_size", self.step_size)
            if not self._move_mount_offset(north, east, step_size):
                logger.warning("Mount: Manual movement failed")
                self.warn(_("Mount did not move!"))
            else:
                label = command.get("label", "")
                self.notify(f"{label} {format_step(step_size)}".strip())

        elif command["type"] == "manual_movement":
            logger.debug("Mount: manual_movement command received")
            direction = command["direction"]
            step_size = command.get("step_size", self.step_size)
            logger.debug(
                f"Mount: Manual movement - direction={direction}, step_size={step_size:.5f}°"
            )
            # Not retrying these.
            if not self._move_mount_manual(direction, step_size):
                logger.warning("Mount: Manual movement failed")
                self.warn(_("Mount did not move!"))

        elif command["type"] == "set_step_size":
            logger.debug("Mount: set_step_size command received")
            step_size = command["step_size"]
            if step_size < 1 / 3600 or step_size > 10.0:
                self.warn(_("Step size wrong"))
                logger.warning(
                    "Mount: Step size out of range - %.5f degrees", step_size
                )
                if step_size < 1 / 3600:
                    self.set_mount_step_size(1 / 3600)
                else:
                    self.set_mount_step_size(10.0)
                logger.debug(
                    "Mount: Step size set to limit %.5f degrees",
                    self.get_mount_step_size(),
                )
            else:
                if not self.set_mount_step_size(step_size):
                    self.warn(_("Cannot set step size!"))
                else:
                    self.step_size = step_size
                    logger.debug("Mount: Step size set to %.5f degrees", self.step_size)

        elif command["type"] == "reduce_step_size":
            logger.debug("Mount: reduce_step_size command received")
            self.step_size = max(
                1 / 3600, self.step_size / 2
            )  # Minimum step size of 1 arcsec
            logger.debug(
                "Mount: Reduce step size - new step size = %.5f degrees",
                self.get_mount_step_size(),
            )
            self.notify(_("Step") + " " + format_step(self.step_size))

        elif command["type"] == "increase_step_size":
            logger.debug("Mount: increase_step_size command received")
            self.step_size = min(
                10.0, self.step_size * 2
            )  # Maximum step size of 10 degrees
            logger.debug(
                "Mount: Increase step size - new step size = %.5f degrees",
                self.step_size,
            )
            self.notify(_("Step") + " " + format_step(self.step_size))

        elif command["type"] == "spiral_search":
            logger.debug("Mount: spiral_search command received")
            raise NotImplementedError("Spiral search not yet implemented.")

        elif command["type"] == "reload_config":
            logger.debug("Mount: reload_config command received")
            self.reload_settings()

        elif command["type"] == "init":
            logger.debug("Mount: init command received")
            # Sync to the last plate solve after the init, if there is one.
            latest = self.latest_solve()
            if latest is not None:
                self.init_solve_ra, self.init_solve_dec, _solve_time = latest
            # Set state to MOUNT_INIT_TELESCOPE to trigger re-initialization
            self.state = MountControlPhases.MOUNT_INIT_TELESCOPE

    def _process_phase(
        self, retry_count: int = 3, delay: float = 1.0
    ) -> Iterator[None]:
        """Command the mount based on the current phase

        This is a generator function that yields control back to the main loop to allow for processing of UI commands
        """

        if self.state == MountControlPhases.MOUNT_UNKNOWN:
            # Do nothing, until we receive a command to initialize the mount.
            return
        if self.state == MountControlPhases.MOUNT_INIT_TELESCOPE:
            while retry_count > 0 and not self.init_mount(
                solve_ra_deg=self.init_solve_ra, solve_dec_deg=self.init_solve_dec
            ):
                start_time = time.time()  # Used for determining timeouts for retries.
                # Wait for delay before retrying
                while time.time() - start_time <= delay:
                    yield
                retry_count -= 1
                if retry_count <= 0:
                    logger.error("Failed to initialize mount.")
                    self.warn(self._last_error or _("Mount no init!"))
                    self.state = MountControlPhases.MOUNT_UNKNOWN
                    if not self.disconnect_mount():
                        logger.error("Failed to disconnect mount.")
                        self.warn(_("Disconnect mount!"))
                    return
                else:
                    logger.warning(
                        "Retrying mount initialization. Attempts left: %d", retry_count
                    )
                    yield
            # Clear the init solve coordinates after successful initialization
            self.init_solve_ra = None
            self.init_solve_dec = None
            # init_mount sets the sidereal track mode.
            self.track_rate = track_rates.SIDEREAL
            self.state = MountControlPhases.MOUNT_TRACKING
            logger.debug("Phase: -> MOUNT_TRACKING")
            self._last_error = ""
            self.notify(_("Mount ready"))
            return

        elif (
            self.state == MountControlPhases.MOUNT_STOPPED
            or self.state == MountControlPhases.MOUNT_TRACKING
        ):
            # Wait for user command to move to target
            # When that is received, the state will be changed to MOUNT_TARGET_ACQUISITION_MOVE
            return

        elif self.state == MountControlPhases.MOUNT_TARGET_FOLLOW:
            self._follow_step(self.clock())
            return
        elif self.state == MountControlPhases.MOUNT_RA_ROTATION:
            # check_motion_timeout watches the rotation in every phase.
            return
        elif self.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE:
            # Wait for mount to reach target
            if self.target_reached:
                logger.debug("Phase: -> MOUNT_TARGET_ACQUISITION_REFINE")
                self.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE
                self._refine_after = time.time() + self.refine_settle_s
                self.target_reached = False
                self.notify(_("Target reached"))
                return
            # If mount is stopped during move, self.state will be changed to MOUNT_STOPPED by the command.

            if not self.is_mount_moving():
                logger.warning(
                    "Phase: Mount is not moving but has not reached target, assuming Refinement needed."
                )
                self.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE
                self._refine_after = time.time() + self.refine_settle_s
                return

        elif self.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE:
            # Mount should not be moving in this state:
            if self.is_mount_moving():
                self.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE
                logger.debug(
                    "Phase: -> MOUNT_TARGET_ACQUISITION_MOVE (mount was still moving)"
                )
                return

            # Wait for a plate solve taken after the mount settled.
            wait_start = time.time()
            solve = self.latest_solve()
            while solve is None or solve[2] < self._refine_after:
                if self.is_mount_moving():
                    # A solve taken now would have slew blur, or be at the
                    # wrong place.
                    self.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE
                    logger.debug("Phase REFINE: mount moves, back to MOVE")
                    return
                if self.state != MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE:
                    logger.debug(
                        "PHASE REFINE: State changed to %s, aborting wait for solve.",
                        self.state,
                    )
                    return
                if time.time() - wait_start > self.refine_solve_timeout_s:
                    logger.error("Phase REFINE: no solve after the move.")
                    self.warn(_("Solve failed!"))
                    self.state = MountControlPhases.MOUNT_TRACKING
                    logger.debug("Phase: -> MOUNT_TRACKING")
                    return
                yield
                solve = self.latest_solve()

            solve_ra, solve_dec, _solve_time = solve
            assert self.target_ra is not None and self.target_dec is not None
            ra_diff = (solve_ra - self.target_ra + 180.0) % 360.0 - 180.0
            dec_diff = solve_dec - self.target_dec
            logger.debug(
                "Phase REFINE: solve RA=%f Dec=%f, off by RA=%f Dec=%f",
                solve_ra,
                solve_dec,
                ra_diff,
                dec_diff,
            )
            if abs(ra_diff) <= 0.01 and abs(dec_diff) <= 0.01:
                # Within 0.01 degrees (36 arcsec) in both axes, the resolution
                # that the UI shows.
                logger.info(
                    "Phase REFINE: Target acquired within 0.01 degrees on both axes, starting drift compensation."
                )
                self.state = MountControlPhases.MOUNT_DRIFT_COMPENSATION
                # Reset drift compensation data when entering this phase
                self._reset_drift_compensation_data()
                self.notify(_("On target"))
                return
            elif self._refine_count >= self.refine_max_iterations:
                logger.warning(
                    "Phase REFINE: still off target after %d refinements.",
                    self._refine_count,
                )
                self.warn(_("Refine stopped"))
                self.state = MountControlPhases.MOUNT_TRACKING
                return
            else:
                # We are off by more than 0.01 degrees in at least one axis, so we need to sync the mount and move again.
                logger.info(
                    "Phase REFINE: Sync mount to solved position and move again."
                )
                retries = retry_count  # reset retry count
                while (
                    retries > 0
                    and not self.sync_mount(solve_ra, solve_dec)
                    and self.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE
                ):
                    if self.state != MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE:
                        logger.debug(
                            "PHASE REFINE: State changed to %s, aborting sync.",
                            self.state,
                        )
                        return  # State changed, exit
                    # Wait for delay before retrying
                    start_time = (
                        time.time()
                    )  # Used for determining timeouts for retries.
                    while (
                        time.time() - start_time <= delay
                        and self.state
                        == MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE
                    ):
                        yield
                    retries -= 1
                    if retries <= 0:
                        logger.error(
                            "Phase REFINE: Failed to sync mount after move (after retrying)."
                        )
                        self.warn(_("Cannot sync mount!"))
                        self.state = MountControlPhases.MOUNT_STOPPED
                        return
                    elif (
                        self.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE
                    ):
                        logger.warning(
                            "Phase REFINE: Retrying to sync mount. Attempts left: %d",
                            retries,
                        )
                        yield

                logger.info("Phase REFINE: Sync successful.")

                ##
                ## Now move again to the original target position
                ##
                retries = retry_count  # reset retry count
                while (
                    retry_count > 0
                    and not self.move_mount_to_target(self.target_ra, self.target_dec)
                    and self.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE
                ):
                    if self.state != MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE:
                        logger.debug(
                            "PHASE REFINE: State changed to %s, aborting move.",
                            self.state,
                        )
                        return  # State changed, exit

                    # Wait for delay before retrying
                    start_time = time.time()
                    while (
                        time.time() - start_time <= delay
                        and self.state
                        == MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE
                    ):
                        yield
                    retry_count -= 1
                    if retry_count <= 0:
                        logger.error(
                            "Failed to command mount to move to target (after retrying)."
                        )
                        self.warn(_("Cannot move to target!"))
                        self.state = MountControlPhases.MOUNT_TRACKING
                        return
                    elif (
                        self.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE
                    ):
                        logger.warning(
                            "Retrying to move mount to target. Attempts left: %d",
                            retry_count,
                        )
                        yield
                logger.info("Phase REFINE: Move to target command successful.")
                self._refine_count += 1
                self.notify(
                    _("Refining {n}/{total}").format(
                        n=self._refine_count, total=self.refine_max_iterations
                    )
                )
                self.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE
                return

        elif self.state == MountControlPhases.MOUNT_DRIFT_COMPENSATION:
            # Handle drift compensation by collecting solve data over time
            # and applying drift rates based on linear regression.
            # The fit starts when the solves span most of
            # drift_compensation_window. Each new solve repeats the fit.
            # An axis with a slope of at least DRIFT_SIGNIFICANCE_SE
            # standard errors gets DRIFT_CORRECTION_GAIN of its drift as a
            # correction, and a new window starts. Without such an axis the
            # window grows up to DRIFT_WINDOW_MAX_S, then a new window
            # starts.

            ###
            ### Data Collection
            ###

            # The frequency, with which we get here is about 10 times per second (determined by the wait in run())
            #

            # Check if we have a solution available
            latest = self.latest_solve()
            if latest is None:
                # No solution available yet, wait
                yield
                return

            ra_target, dec_target, solve_time = latest
            if self.drift_solve_times and self.drift_solve_times[-1] == solve_time:
                # No new solve.
                return
            if (
                self._drift_used_until is not None
                and solve_time <= self._drift_used_until
            ):
                # The last window used this solve.
                return
            if self.drift_solve_ra:
                first_ra = self.drift_solve_ra[0]
                ra_target = first_ra + (ra_target - first_ra + 180.0) % 360.0 - 180.0
            self.drift_solve_times.append(solve_time)
            self.drift_solve_ra.append(ra_target)
            self.drift_solve_dec.append(dec_target)

            ###
            ### Data Analysis and Drift Rate Adjustment
            ###

            time_span = self.drift_solve_times[-1] - self.drift_solve_times[0]
            max_window = max(DRIFT_WINDOW_MAX_S, self.drift_compensation_window)
            if (
                len(self.drift_solve_times) < DRIFT_MIN_SOLVES
                or time_span < self.drift_compensation_window * DRIFT_WINDOW_FILL
            ):
                if time_span >= max_window:
                    # Too few solves in the longest window.
                    self._start_drift_window()
                return

            # Times relative to the first solve keep the sums small.
            t0 = self.drift_solve_times[0]
            times = [t - t0 for t in self.drift_solve_times]
            ra_slope, _intercept_ra, ra_se = self._compute_linear_fit(
                times, self.drift_solve_ra
            )
            dec_slope, _intercept_dec, dec_se = self._compute_linear_fit(
                times, self.drift_solve_dec
            )
            logger.debug(
                "Drift compensation: %d solves over %.1fs, "
                'RA %+.2f"/s (SE %.2f), Dec %+.2f"/s (SE %.2f)',
                len(times),
                time_span,
                ra_slope * 3600.0,
                ra_se * 3600.0,
                dec_slope * 3600.0,
                dec_se * 3600.0,
            )
            cos_dec = math.cos(math.radians(self.drift_solve_dec[-1]))
            ra_adjustment, ra_adjustment_se = self._drift_correction(
                ra_slope, ra_se, cos_dec
            )
            dec_adjustment, dec_adjustment_se = self._drift_correction(
                dec_slope, dec_se, 1.0
            )

            if ra_adjustment == 0.0 and dec_adjustment == 0.0:
                if time_span >= max_window:
                    logger.info(
                        "Drift compensation: no significant drift in %.0fs, new window.",
                        time_span,
                    )
                    self._start_drift_window()
                return

            logger.info(
                'Drift compensation: drift RA %+.2f"/s Dec %+.2f"/s over %.1fs, '
                'correction RA %+.2f"/s Dec %+.2f"/s',
                ra_slope * 3600.0,
                dec_slope * 3600.0,
                time_span,
                ra_adjustment * 3600.0,
                dec_adjustment * 3600.0,
            )
            retries = retry_count
            while retries > 0 and not self.adjust_mount_drift_rates(
                ra_adjustment,
                dec_adjustment,
                ra_se=ra_adjustment_se,
                dec_se=dec_adjustment_se,
            ):
                # Wait for delay before retrying
                start_time = time.time()
                while time.time() - start_time <= delay:
                    yield
                retries -= 1
                if retries <= 0:
                    logger.error("Failed to adjust drift rates after retrying.")
                    self.warn(_("Drift failure!"))
                    self.state = MountControlPhases.MOUNT_TRACKING
                    self._start_drift_window()
                    return
                else:
                    logger.warning(
                        "Retrying to adjust drift rates. Attempts left: %d",
                        retries,
                    )
                    yield
            # The rates changed: measure the drift again in a new window.
            self._start_drift_window()
            return
        elif self.state == MountControlPhases.MOUNT_SPIRAL_SEARCH:
            # Handle spiral search state
            return
        else:
            logger.error(f"Unknown mount state: {self.state}")
            return

    def run(self):
        """Main loop to manage mount control operations.

        This is called in a separate process and manages the main mount control loop.

        The commands that are supported are:
        - Stop Movement
        - Goto Target
        - Manual Movement (in 4 directions)
        - Reduce Step Size
        - Increase Step Size
        - Spiral Search

        """
        logger.info("Starting mount control.")
        # Setup back-off and retry logic for initialization
        # TODO implement back-off and retry logic

        cmd_steps = 0
        phase_steps = 0
        try:
            command_step = None
            phase_step = None
            while True:
                self.periodic_mount_task()
                self.refresh_track_rate()
                self.check_motion_timeout()
                self.publish_status()

                #
                # Process commands from UI
                #
                try:
                    # Process retries
                    if command_step is not None:
                        try:
                            next(command_step)
                            cmd_steps += 1
                        except StopIteration:
                            command_step = (
                                None  # Finished processing the current command
                            )

                    # Check for new commands if not currently processing one
                    if command_step is None:
                        command = self.mount_queue.get(block=False)
                        command_step = self._process_command(command)

                except queue.Empty:
                    # No command in queue, continue with state-based processing
                    pass

                #
                # State-based processing
                #

                if phase_step is not None:
                    try:
                        next(phase_step)
                        phase_steps += 1
                    except StopIteration:
                        phase_step = None  # Finished processing the current phase step

                if phase_step is None:
                    phase_step = self._process_phase()

                # Sleep for rate.
                time.sleep(0.1)
                # if (cmd_steps+phase_steps)%10 == 0:
                #     logger.debug(
                #         f"Mount control loop: {cmd_steps} command steps, {phase_steps} phase steps"
                #     )
                #     logger.debug(f"Mount state: {self.state}")
        except SystemExit:
            # The exit command ends the loop. A return ends the process (or
            # the thread in a test) with no unhandled exception.
            logger.info("Mount control stopped.")
            return
        except KeyboardInterrupt:
            self._stop_motion()
            self.disconnect_mount()
            print("Mount control stopped.")
            raise
