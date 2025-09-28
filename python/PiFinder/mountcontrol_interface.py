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
import time

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
    MOUNT_INIT_TELESCOPE = auto()
    MOUNT_STOPPED = auto()
    MOUNT_TARGET_ACQUISITION_MOVE = auto()
    MOUNT_TARGET_ACQUISITION_REFINE = auto()
    MOUNT_DRIFT_COMPENSATION = auto()
    MOUNT_TRACKING = auto()
    MOUNT_SPIRAL_SEARCH = auto()

class MountDirectionsAltAz(Enum):
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

class MountDirectionsEquatorial(Enum):
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
    MountControlBase is an abstract base class for telescope mount control interfaces.
    This class defines the required interface and shared logic for controlling a telescope mount.
    Responsibilities:
    - Provide abstract methods for mount initialization, synchronization, movement, drift rate control, spiral search, and manual movement.
    - Provide notification methods for subclasses to report mount state changes (position updates, target reached, stopped).
        The `run` method manages the main control loop, calling `init_mount` on startup and
    """
    Base class for mount control interfaces.

    This class defines the interface and shared logic for controlling a telescope mount.
    It is intended to be subclassed by specific mount implementations, which must override
    the abstract methods to provide hardware-specific functionality.
    
    Responsibilities of MountControlBase:
    - Manage shared state, communication queues, and logging for mount control.
    - Define the main control loop (`run`) and initialization sequence.
    - Provide abstract methods for mount initialization, disconnection, movement, and position retrieval.

    Responsibilities of subclasses:
    - Implement hardware-specific logic of mount by overwriting the below methods. 
    - Handle communication with the actual mount hardware or protocol.

    Abstract methods to override in subclasses:
        init_mount(): Initialize the mount hardware and prepare for operation.
        sync_mount(current_position_radec): Synchronize the mount's pointing state.
        move_mount_to_target(target_position_radec): Move the mount to the specified target position.
        set_mount_drift_rates(drift_rate_ra, drift_rate_dec): Set the mount's drift rates.
        spiral_search(center_position_radec, max_radius_deg, step_size_deg): Perform a spiral search.
        move_mount_manual(direction, speed): Move the mount manually in a specified direction and speed.

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

    def __init__(self, mount_queue, console_queue, shared_state, log_queue, verbose=False):
        """     
        Args:
            mount_queue: Queue for receiving target positions or commands.
            console_queue: Queue for sending messages to the user interface or console.
            shared_state: Shared state object for inter-process communication.
            log_queue: Queue for logging messages.
            verbose (bool): Enable verbose logging if True.

        Attributes:
            state: Current state of the mount (e.g., initialization, tracking).
            verbose: Verbosity flag for logging and debugging.
        """
        self.mount_queue = mount_queue
        self.console_queue = console_queue
        self.shared_state = shared_state
        self.log_queue = log_queue
        self.verbose = verbose

        self.state = MountControlPhases.MOUNT_INIT_TELESCOPE

    # 
    # Methods to be overridden by subclasses for controlling the specifics of a mount
    # 

    def init_mount(self) -> bool:
        """ Initialize the mount, so that we receive updates and can send commands.

        The subclass needs to set up the mount and prepare it for operation. 
        This may include connecting to the mount, setting initial parameters, un-parking, etc.

        The subclass needs to return a boolean indicating success or failure.
        A failure will cause the main loop to retry initialization after a delay.
        If the mount cannot be initialized, throw an exception to abort the process.
        This will be used to inform the user via the console queue.

        Returns:
            bool: True if initialization was successful, False otherwise.
        """
        raise NotImplementedError("This method should be overridden by subclasses.")

    def sync_mount(self, current_position_radec) -> bool:
        """ Synchronize the mount's pointing state with the current position PiFinder is looking at.

        The subclass needs to return a boolean indicating success or failure.
        A failure will cause the main loop to retry synchronization after a delay.
        If the mount cannot be synchronized, throw an exception to abort the process.
        This will be used to inform the user via the console queue. 

        Returns:
            bool: True if synchronization was successful, False otherwise.
        """
        raise NotImplementedError("This method should be overridden by subclasses.")

    def move_mount_to_target(self, target_position_radec) -> bool:
        """ Move the mount to the specified target position.

        The subclass needs to return a boolean indicating success or failure, 
        if the command was successfully sent.
        A failure will cause the main loop to retry movement after a delay.
        If the mount cannot be moved, throw an exception to abort the process.
        This will be used to inform the user via the console queue.

        Returns:
            bool: True if movement was successful, False otherwise.
        """
        raise NotImplementedError("This method should be overridden by subclasses.")

    def set_mount_drift_rates(self, drift_rate_ra, drift_rate_dec) -> bool:
        """ Set the mount's drift rates in RA and DEC.

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
    
    def move_mount_manual(self, direction, speed) -> bool:
        """ Move the mount manually in the specified direction at the given speed.

        The subclass needs to return a boolean indicating success or failure, 
        if the command was successfully sent.
        A failure will cause the main loop to retry the manual movement command after a delay.
        If the mount cannot perform the manual movement, throw an exception to abort the process.
        This will be used to inform the user via the console queue.

        Args:
            direction: The direction to move (e.g., 'up', 'down', 'left', 'right').
            speed: The speed at which to move.
        Returns:
            bool: True if manual movement command was successful, False otherwise.

        """
        raise NotImplementedError("This method should be overridden by subclasses.")

    #
    # Methods to be called by subclasses to inform the base class of mount state changes
    #

    def mount_current_position(self, current_mount_position_radec) -> None:
        """ Receive the current position of the mount from subclasses. 
        
        This method needs to be called by the subclass whenever it receives an update of the position from the mount.
        This will be used to update the target UI and show the current position to the user (i.e. update the arrow display).
        
        """
        # TODO implement
        pass
    
    def mount_target_reached(self) -> None:
        """ Notification that the mount has reached the target position and stopped slewing.

        This method needs to be called by the subclass whenever it detects that the mount has reached the target position.
        This will be used to transition to the next phase in the control loop.

        """
        # TODO implement
        pass

    def mount_stopped(self) -> None:
        """ Notification that the mount has stopped. 

        This method needs to be called by the subclass whenever it detects that the mount has stopped and is not moving anymore. 
        Even if it has not reached the target position. The mount must not be tracking, too.

        This will be used to transition to the MOUNT_STOPPED phase in the control loop.
        """
        # TODO implement
        pass

    # Main loop and shared logic
    #

    def spiral_search(self, center_position_radec, max_radius_deg, step_size_deg) -> None:
        """ Commands the mount to perform a spiral search around the center position.
        """
        raise NotImplementedError("This method should be overridden by subclasses.")
    
    def run(self):
        """ Main loop to manage mount control operations."""
        self.init()
        try:
            while True:
                # TODO: Implement the main control loop logic here.
                # This will involve checking the current state, processing commands from the mount_queue,
                # and calling the appropriate methods based on the current phase.
                time.sleep(1)
        except KeyboardInterrupt:
            self.disconnect()
            print("Mount control stopped.")
            raise