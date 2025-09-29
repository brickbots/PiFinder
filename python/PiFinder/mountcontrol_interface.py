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
from queue import Queue
import time

from python.PiFinder.state import SharedStateObj
import PiFinder.i18n  # noqa: F401

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

class MountDirections(Enum):
    """ Base class for mount directions enumerations. """
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

    def __init__(self, mount_queue: Queue, console_queue: Queue, shared_state: SharedStateObj, log_queue: Queue):
        """     
        Args:
            mount_queue: Queue for receiving target positions or commands.
            console_queue: Queue for sending messages to the user interface or console.
            shared_state: SharedStateObj for inter-process communication with other PiFinder components.
            log_queue: Queue for logging messages.

        Attributes:
            state: Current state of the mount (e.g., initialization, tracking).
        """
        self.mount_queue = mount_queue
        self.console_queue = console_queue
        self.shared_state = shared_state
        self.log_queue = log_queue

        self.target_ra = None # Target Right Ascension in degrees, or None
        self.target_dec = None # Target Declination in degrees, or None

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

    def stop_mount(self) -> bool:
        """ Stop any current movement of the mount.

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
        """ Move the mount to the specified target position.

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

    def disconnect_mount(self) -> bool:
        """ Safely disconnect from the mount hardware.

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

        This will be used to transition to the MOUNT_STOPPED phase in the control loop, regardless of the previous phase.
        """
        # TODO implement
        pass

    #
    # Shared logic and main loop 
    #

    def spiral_search(self, center_position_radec, max_radius_deg, step_size_deg) -> None:
        """ Commands the mount to perform a spiral search around the center position.
        """
        raise NotImplementedError("Not yet implemented.")
    
    def run(self):
        """ Main loop to manage mount control operations.
        
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
        
        try:
            while True:
                try:
                    # Try to get a command from the queue (non-blocking)
                    command = self.mount_queue.get(block=False)
                    
                    # Process the command based on its type
                    if command["type"] == 'exit':
                        # This is here for debugging and testing purposes.
                        logger.warning("Mount control exiting on command.")
                        self.stop_mount()
                        self.disconnect_mount()
                        return
                    
                    elif command['type'] == 'stop_movement':
                        logger.debug("Mount: stop command received")
                        retry_count = 3
                        while retry_count > 0 and not self.stop_mount():
                            time.sleep(2) # Retry after a delay
                            retry_count -= 1
                            if retry_count == 0:
                                logger.error("Failed to stop mount after retrying. Re-initializing mount.")
                                self.console_queue.put(["WARNING", _("Cannot stop mount!")])
                                self.state = MountControlPhases.MOUNT_INIT_TELESCOPE
                            else:
                                logger.warning("Retrying to stop mount. Attempts left: %d", retry_count)

                            ## TODO CONTINUE HERE

                    elif command['type'] == 'goto_target':
                        target_ra = command['ra']
                        target_dec = command['dec']
                        logger.debug(f"Mount: Goto target - RA={target_ra}, DEC={target_dec}")
                        retry_count = 3
                        while retry_count > 0 and not self.move_mount_to_target(target_ra, target_dec):
                            time.sleep(2) # Retry after a delay
                            retry_count -= 1
                            if retry_count == 0:
                                logger.error("Failed to command mount to move to target.")
                                self.console_queue.put(["WARNING", _("Cannot move to target!")])
                                self.stop_mount()
                                self.state = MountControlPhases.MOUNT_STOPPED
                            else:
                                logger.warning("Retrying to move mount to target. Attempts left: %d", retry_count)
                                # self.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE
                            
                    elif command['type'] == 'manual_movement':
                        direction = command['direction']
                        speed = command.get('speed', 1.0)
                        logger.info(f"Manual movement command: direction={direction}, speed={speed}")
                        if self.state != MountControlPhases.MOUNT_INIT_TELESCOPE:
                            self.move_mount_manual(direction, speed)
                            self.state = MountControlPhases.MOUNT_TRACKING
                            
                    elif command['type'] == 'reduce_step_size':
                        logger.info("Reduce step size command received")
                        # TODO: Implement step size reduction logic
                        
                    elif command['type'] == 'increase_step_size':
                        logger.info("Increase step size command received")
                        # TODO: Implement step size increase logic
                        
                    elif command['type'] == 'spiral_search':
                        center_ra = command['center_ra']
                        center_dec = command['center_dec']
                        max_radius = command.get('max_radius_deg', 1.0)
                        step_size = command.get('step_size_deg', 0.1)
                        logger.info(f"Mount: Spiral search - center=({center_ra}, {center_dec})")
                        self.spiral_search((center_ra, center_dec), max_radius, step_size)
                        if self.state != MountControlPhases.MOUNT_INIT_TELESCOPE:
                            self.state = MountControlPhases.MOUNT_SPIRAL_SEARCH
                            
                except Queue.Empty:
                    # No command in queue, continue with state-based processing
                    pass

                if self.state == MountControlPhases.MOUNT_INIT_TELESCOPE:
                    success = self.init_mount()
                    if success:
                        self.state = MountControlPhases.MOUNT_STOPPED
                        logger.debug("Mount initialized successfully.")
                    else:
                        logger.error("Mount initialization failed. Retrying...")
                        
                elif self.state == MountControlPhases.MOUNT_STOPPED:
                    # Wait for user command to move to target
                    pass
                elif self.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE:
                    # Handle target acquisition movement
                    pass
                elif self.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE:
                    # Handle target acquisition refinement
                    pass
                elif self.state == MountControlPhases.MOUNT_DRIFT_COMPENSATION:
                    # Handle drift compensation
                    pass
                elif self.state == MountControlPhases.MOUNT_TRACKING:
                    # Handle tracking state
                    pass
                elif self.state == MountControlPhases.MOUNT_SPIRAL_SEARCH:
                    # Handle spiral search state
                    pass
                # TODO: Implement the main control loop logic here.
                # This will involve checking the current state, processing commands from the mount_queue,
                # and calling the appropriate methods based on the current phase.
                time.sleep(1)
        except KeyboardInterrupt:
            self.disconnect()
            print("Mount control stopped.")
            raise