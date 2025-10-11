# (C) 2025 Jens Scheidtmann
#
# This file is part of PiFinder.
#
# PiFinder is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import logging
from enum import Enum, auto
import queue
from multiprocessing import Queue
import sys
import time
from typing import TYPE_CHECKING, Generator, Iterator, Optional, Any

from PiFinder.state import SharedStateObj

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
        set_mount_drift_rates(drift_rate_ra, drift_rate_dec): Set the mount's drift rates.
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
        self.init_solve_dec: Optional[float] = None  # Solved Dec for mount initialization

        self.state: MountControlPhases = MountControlPhases.MOUNT_INIT_TELESCOPE

    #
    # Methods to be overridden by subclasses for controlling the specifics of a mount
    #

    def init_mount(
        self,
        latitude_deg: Optional[float] = None,
        longitude_deg: Optional[float] = None,
        elevation_m: Optional[float] = None,
        utc_time: Optional[str] = None,
        solve_ra_deg: Optional[float] = None,
        solve_dec_deg: Optional[float] = None,
    ) -> bool:
        """Initialize the mount, so that we receive updates and can send commands.

        The subclass needs to set up the mount and prepare it for operation.
        This may include connecting to the mount, setting initial parameters, un-parking, etc.
        It should also set the geographic coordinates and UTC time if provided.
        If solve_ra_deg and solve_dec_deg are provided, the mount should sync to that position.

        The subclass needs to return a boolean indicating success or failure.
        A failure will cause the main loop to retry initialization after a delay.
        If the mount cannot be initialized, throw an exception to abort the process.
        This will be used to inform the user via the console queue.

        Args:
            latitude_deg: Observatory latitude in degrees (positive North). Optional.
            longitude_deg: Observatory longitude in degrees (positive East). Optional.
            elevation_m: Observatory elevation in meters above sea level. Optional.
            utc_time: UTC time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS). Optional.
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

    def set_mount_drift_rates(self, drift_rate_ra, drift_rate_dec) -> bool:
        """Set the mount's drift rates in RA and DEC.

        Expectation is that the mount immediately starts applying the drift rates.

        The subclass needs to return a boolean indicating success or failure,
        if the command was successfully sent.
        A failure will cause the main loop to retry setting the rates after a delay.
        If the mount cannot set the drift rates, throw an exception to abort the process.
        This will be used to inform the user via the console queue.

        Returns:
            bool: True if setting drift rates was successful, False otherwise.
        """
        raise NotImplementedError("This method should be overridden by subclasses.")

    def move_mount_manual(
        self, direction: MountDirections, slew_rate: str, duration: float
    ) -> bool:
        """Move the mount manually in the specified direction using the mount's current step size.

        The subclass needs to return a boolean indicating success or failure,
        if the command was successfully sent.
        A failure will be reported back to the user.

        Args:
            direction: The direction to move see MountDirections and its subclasses.
            slew_rate: The slew rate used to move the mount.
            duration: Duration in seconds to move the mount.
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
        self.state = MountControlPhases.MOUNT_STOPPED

    #
    # Helper methods to decorate mount control methods with state management
    #
    def _stop_mount(self) -> bool:
        if self.state != MountControlPhases.MOUNT_STOPPED:
            return self.stop_mount()  # State is set in mount_stopped() callback
        else:
            logger.debug("Mount already stopped, not sending stop command")
            return True

    def _move_mount_manual(
        self, direction: MountDirections, slew_rate: str, duration: float
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

        success = self.move_mount_manual(direction, slew_rate, duration)
        if success:
            if (
                self.state != MountControlPhases.MOUNT_TRACKING
                and self.state != MountControlPhases.MOUNT_DRIFT_COMPENSATION
            ):
                self.state = MountControlPhases.MOUNT_TRACKING
                logger.debug("Phase: -> MOUNT_TRACKING due to manual movement")
        return success

    def _goto_target(self, target_ra, target_dec) -> bool:
        success = self.move_mount_to_target(target_ra, target_dec)
        if success:
            self.target_reached = False
            self.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE
            logger.debug(
                f"Phase: -> MOUNT_TARGET_ACQUISITION_MOVE to RA={target_ra}, DEC={target_dec}"
            )
        return success

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

    def _process_command(
        self, command, retry_count: int = 3, delay: float = 2.0
    ) -> Generator:
        """Process a command received from the mount queue.
        This is a generator function that yields control back to the main loop to allow for mount state processing and retries.
        This function does not call mount control methods directly, but calls internal helper functions that in addition manage state.
        The only exception is when retrying failed and we need to change the state to MOUNT_INIT_TELESCOPE or MOUNT_STOPPED.
        """

        start_time = time.time()  # Used for determining timeouts for retries.
        # Process the command based on its type
        if command["type"] == "exit":
            # This is here for debugging and testing purposes.
            logger.warning("Mount control exiting on command.")
            self._stop_mount()
            sys.exit(0)
            # raise KeyboardInterrupt("Mount control exiting on command.")

        elif command["type"] == "stop_movement":
            logger.debug("Mount: stop command received")
            while retry_count > 0 and not self._stop_mount():
                # Wait for delay before retrying
                while time.time() - start_time <= delay:
                    yield
                retry_count -= 1
                if retry_count == 0:
                    logger.error(
                        "Failed to stop mount after retrying. Re-initializing mount."
                    )
                    self.console_queue.put(["WARNING", _("Cannot stop mount!")])
                    self.state = MountControlPhases.MOUNT_INIT_TELESCOPE
                else:
                    logger.warning(
                        "Retrying to stop mount. Attempts left: %d", retry_count
                    )
                    yield

        elif command["type"] == "sync":
            logger.debug("Mount: sync command received")
            sync_ra = command["ra"]
            sync_dec = command["dec"]
            logger.debug(f"Mount: Syncing - RA={sync_ra}, DEC={sync_dec}")
            while retry_count > 0 and not self.sync_mount(sync_ra, sync_dec):
                # Wait for delay before retrying
                while time.time() - start_time <= delay:
                    yield
                retry_count -= 1
                if retry_count == 0:
                    logger.error(
                        "Failed to sync mount after retrying. Re-initializing."
                    )
                    self.console_queue.put(["WARNING", _("Cannot sync mount!")])
                    self.state = MountControlPhases.MOUNT_INIT_TELESCOPE
                else:
                    logger.warning(
                        "Retrying to sync mount. Attempts left: %d", retry_count
                    )
                    yield

        elif command["type"] == "goto_target":
            logger.debug("Mount: goto_target command received")
            self.target_ra = command["ra"]
            self.target_dec = command["dec"]
            logger.debug(
                f"Mount: Goto target - RA={self.target_ra}, DEC={self.target_dec}"
            )
            retry_stop = retry_count  # store for later waits
            while retry_count > 0 and not self._goto_target(
                self.target_ra, self.target_dec
            ):
                # Wait for delay before retrying
                while time.time() - start_time <= delay:
                    yield
                retry_count -= 1
                if retry_count == 0:
                    logger.error("Failed to command mount to move to target.")
                    self.console_queue.put(
                        ["WARNING", _("Cannot move to target!\nStopping!")]
                    )
                    # Try to stop the mount.
                    logger.warning(
                        f"Stopping mount after failed goto_target. {retry_stop} retries"
                    )
                    stop_mount_cmd = self._process_command(
                        {"type": "stop_movement"}, retry_stop, delay
                    )
                    try:
                        while next(stop_mount_cmd):
                            pass
                    except StopIteration:
                        pass
                else:
                    logger.warning(
                        "Retrying to move mount to target. Attempts left: %d",
                        retry_count,
                    )
                    yield

        elif command["type"] == "manual_movement":
            logger.debug("Mount: manual_movement command received")
            direction = command["direction"]
            slew_rate = command["slew_rate"]
            duration = command["duration"]
            logger.debug(f"Mount: Manual movement - direction={direction}")
            # Not retrying these.
            if not self._move_mount_manual(direction, slew_rate, duration):
                logger.warning("Mount: Manual movement failed")
                self.console_queue.put(["WARNING", _("Mount did not move!")])

        elif command["type"] == "set_step_size":
            logger.debug("Mount: set_step_size command received")
            step_size = command["step_size"]
            if step_size < 1 / 3600 or step_size > 10.0:
                self.console_queue.put(
                    ["WARNING", _("Step size must be between 1 arcsec and 10 degrees!")]
                )
                logger.warning(
                    "Mount: Step size out of range - %.5f degrees", step_size
                )
            else:
                logger.debug(f"Mount: Set step size - {step_size} degrees")
                if not self.set_mount_step_size(step_size):
                    self.console_queue.put(["WARNING", _("Cannot set step size!")])
                else:
                    self.step_size = step_size
                    logger.debug("Mount: Step size set to %.5f degrees", self.step_size)

        elif command["type"] == "reduce_step_size":
            logger.debug("Mount: reduce_step_size command received")
            self.step_size = max(
                1 / 3600, self.step_size / 2
            )  # Minimum step size of 1 arcsec
            logger.debug(
                "Mount: Reduce step size - new step size = %.5f degrees", self.step_size
            )

        elif command["type"] == "increase_step_size":
            logger.debug("Mount: increase_step_size command received")
            self.step_size = min(
                10.0, self.step_size * 2
            )  # Maximum step size of 10 degrees
            logger.debug(
                "Mount: Increase step size - new step size = %.5f degrees",
                self.step_size,
            )

        elif command["type"] == "spiral_search":
            logger.debug("Mount: spiral_search command received")
            raise NotImplementedError("Spiral search not yet implemented.")

        elif command["type"] == "init":
            logger.debug("Mount: init command received")
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
                    self.console_queue.put(["WARNING", _("Cannot initialize mount!")])
                    self.state = MountControlPhases.MOUNT_UNKNOWN
                    return
                else:
                    logger.warning(
                        "Retrying mount initialization. Attempts left: %d", retry_count
                    )
                    yield
            # Clear the init solve coordinates after successful initialization
            self.init_solve_ra = None
            self.init_solve_dec = None
            self.state = MountControlPhases.MOUNT_TRACKING
            logger.debug("Phase: -> MOUNT_TRACKING")
            return

        elif (
            self.state == MountControlPhases.MOUNT_STOPPED
            or self.state == MountControlPhases.MOUNT_TRACKING
        ):
            # Wait for user command to move to target
            # When that is received, the state will be changed to MOUNT_TARGET_ACQUISITION_MOVE
            return

        elif self.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE:
            # Wait for mount to reach target
            if self.target_reached:
                logger.debug("Phase: -> MOUNT_TARGET_ACQUISITION_REFINE")
                self.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE
                self.target_reached = False
                return
            # If mount is stopped during move, self.state will be changed to MOUNT_STOPPED by the command.

            if not self.is_mount_moving():
                logger.warning(
                    "Phase: Mount is not moving but has not reached target, assuming Refinement needed."
                )
                self.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE
                return

        elif self.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE:
            # Mount should not be moving in this state:
            if self.is_mount_moving():
                self.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE
                logger.debug(
                    "Phase: -> MOUNT_TARGET_ACQUISITION_MOVE (mount was still moving)"
                )
                return

            retries = retry_count
            # Wait until we have a solved image
            while (
                retries > 0
                and self.shared_state.solution() is None
                and self.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE
            ):
                logger.debug(
                    "Phase REFINE: Waiting for solve after move... Attempts left: %d",
                    retries,
                )
                # Wait for delay before retrying
                start_time = time.time()  # Used for determining timeouts for retries.
                while (
                    time.time() - start_time <= delay
                    and self.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE
                ):
                    yield
                # Retries exceeded?
                retries -= 1
                if retries <= 0:
                    logger.error("Failed to solve after move (after retrying).")
                    self.console_queue.put(["WARNING", _("Solve failed!")])
                    self.state = MountControlPhases.MOUNT_TRACKING
                    logger.debug("Phase: -> MOUNT_TRACKING")
                    return
                elif self.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE:
                    logger.debug(
                        "Waiting for solve after move. Attempts left: %d", retry_count
                    )
                    yield
                elif self.state != MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE:
                    logger.debug(
                        "PHASE REFINE: State changed to %s, aborting wait for solve.",
                        self.state,
                    )
                    return  # State changed, exit

            # We have a solution, check how far off we are from the target ...
            solution = self.shared_state.solution()
            logger.debug(
                "Phase REFINE: Solve received. RA_target = %f, Dec_target = %f",
                solution["RA_target"],
                solution["Dec_target"],
            )
            if (
                abs(self.current_ra - solution["RA_target"]) <= 0.01
                and abs(self.current_dec - solution["Dec_target"]) <= 0.01
            ):
                # Target is within 0.01 degrees (36 arcsec) of the solved position in both axes, so we are done.
                # This is the resolution that is displayed in the UI.
                logger.info(
                    "Phase REFINE: Target acquired within 0.01 degrees on both axes, starting drift compensation."
                )
                self.state = MountControlPhases.MOUNT_DRIFT_COMPENSATION
                return
            else:
                # We are off by more than 0.01 degrees in at least one axis, so we need to sync the mount and move again.
                logger.info(
                    "Phase REFINE: Sync mount to solved position and move again."
                )
                retries = retry_count  # reset retry count
                while (
                    retries > 0
                    and not self.sync_mount(
                        solution["RA_target"], solution["Dec_target"]
                    )
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
                        self.console_queue.put(["WARNING", _("Cannot sync mount!")])
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
                        self.console_queue.put(["WARNING", _("Cannot move to target!")])
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
                self.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE
                return

        elif self.state == MountControlPhases.MOUNT_DRIFT_COMPENSATION:
            # Handle drift compensation
            # TODO implement drift compensation logic
            # For now, just stay in this state.
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
        except KeyboardInterrupt:
            self.disconnect_mount()
            print("Mount control stopped.")
            raise
