from multiprocessing import Queue
from typing import List, Optional, Tuple
from PiFinder.mountcontrol_interface import (
    MountControlBase,
    MountDirections,
    MountDirectionsEquatorial,
    MountDirectionsAltAz,
)
import PyIndi
import logging
import time

from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.state import SharedStateObj

logger = logging.getLogger("MountControl.Indi")
clientlogger = logging.getLogger("MountControl.Indi.PyIndi")


#
# source .venv/bin/activate && pip uninstall -y pyindi-client && pip install --no-binary :all: pyindi-client
#
class PiFinderIndiClient(PyIndi.BaseClient):
    """INDI client for PiFinder telescope mount control.

    This client connects to an INDI server and manages communication with
    telescope/mount devices. It automatically detects telescope devices and
    monitors their properties for position updates and movement status.

    The indi client does not keep track of the current position itself, but
    relays updates to the MountControlIndi class to handle position updates
    and target tracking.
    """

    def __init__(self, mount_control):
        super().__init__()
        self.telescope_device = None
        self.mount_control = mount_control

    def _wait_for_property(self, device, property_name, timeout=5.0):
        """Wait for a property to become available on a device.

        Args:
            device: The INDI device
            property_name: Name of the property to wait for
            timeout: Maximum time to wait in seconds

        Returns:
            The property if found, None otherwise.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            prop = device.getProperty(property_name)
            if prop:
                return prop
            time.sleep(0.1)
        clientlogger.warning(
            f"Timeout waiting for property {property_name} on {device.getDeviceName()}"
        )
        return None

    def set_switch(self, device, property_name, element_name, timeout=5.0):
        """Set a switch property element to ON.

        Args:
            device: The INDI device
            property_name: Name of the switch property
            element_name: Name of the switch element to turn ON
            timeout: Maximum time to wait for property

        Returns:
            True if successful, False otherwise.
        """
        # Wait for property to be available
        prop = self._wait_for_property(device, property_name, timeout)
        if not prop:
            clientlogger.error(
                f"Property {property_name} not available on {device.getDeviceName()}"
            )
            return False

        switch_prop = device.getSwitch(property_name)
        if not switch_prop:
            clientlogger.error(
                f"Could not get switch property {property_name} on {device.getDeviceName()}"
            )
            return False

        # Set the switch - turn on the specified element, turn off all others
        for i in range(len(switch_prop)):
            switch = switch_prop[i]
            if switch.name == element_name:
                switch.s = PyIndi.ISS_ON
            else:
                switch.s = PyIndi.ISS_OFF

        self.sendNewSwitch(switch_prop)
        return True

    def set_switch_off(self, device, property_name, timeout=5.0):
        """Set all elements of a switch property to OFF.

        Args:
            device: The INDI device
            property_name: Name of the switch property
            timeout: Maximum time to wait for property

        Returns:
            True if successful, False otherwise.
        """
        # Wait for property to be available
        prop = self._wait_for_property(device, property_name, timeout)
        if not prop:
            clientlogger.error(
                f"Property {property_name} not available on {device.getDeviceName()}"
            )
            return False

        switch_prop = device.getSwitch(property_name)
        if not switch_prop:
            clientlogger.error(
                f"Could not get switch property {property_name} on {device.getDeviceName()}"
            )
            return False

        # Set all switches to OFF
        for i in range(len(switch_prop)):
            switch_prop[i].s = PyIndi.ISS_OFF

        self.sendNewSwitch(switch_prop)
        return True

    def set_number(self, device, property_name, values, timeout=5.0):
        """Set numeric property values.

        Args:
            device: The INDI device
            property_name: Name of the numeric property
            values: Dictionary mapping element names to values
            timeout: Maximum time to wait for property

        Returns:
            True if successful, False otherwise.
        """
        # Wait for property to be available
        prop = self._wait_for_property(device, property_name, timeout)
        if not prop:
            clientlogger.error(
                f"Property {property_name} not available on {device.getDeviceName()}"
            )
            return False

        num_prop = device.getNumber(property_name)
        if not num_prop:
            clientlogger.error(
                f"Could not get number property {property_name} on {device.getDeviceName()}"
            )
            return False

        # Set the values
        for i in range(len(num_prop)):
            num = num_prop[i]
            if num.name in values:
                num.value = values[num.name]

        self.sendNewNumber(num_prop)
        return True

    def set_text(self, device, property_name, values, timeout=5.0):
        """Set text property values.

        Args:
            device: The INDI device
            property_name: Name of the text property
            values: Dictionary mapping element names to string values
            timeout: Maximum time to wait for property

        Returns:
            True if successful, False otherwise.
        """
        # Wait for property to be available
        prop = self._wait_for_property(device, property_name, timeout)
        if not prop:
            clientlogger.error(
                f"Property {property_name} not available on {device.getDeviceName()}"
            )
            return False

        text_prop = device.getText(property_name)
        if not text_prop:
            clientlogger.error(
                f"Could not get text property {property_name} on {device.getDeviceName()}"
            )
            return False

        # Set the values
        for i in range(len(text_prop)):
            text = text_prop[i]
            if text.name in values:
                text.text = values[text.name]

        self.sendNewText(text_prop)
        return True

    def unpark_mount(self, device) -> bool:
        """Unpark the mount if it is parked.

        Args:
            device: The INDI telescope device

        Returns:
            True if unparking succeeded or mount was already unparked, False on error.
        """
        try:
            # Check if mount has TELESCOPE_PARK property
            park_prop = self._wait_for_property(device, "TELESCOPE_PARK", timeout=2.0)
            if not park_prop:
                clientlogger.debug("Mount does not have TELESCOPE_PARK property, assuming not parked")
                return True

            # Get the park switch property
            park_switch = device.getSwitch("TELESCOPE_PARK")
            if not park_switch:
                clientlogger.warning("Could not get TELESCOPE_PARK switch property")
                return True

            # Check if mount is parked
            is_parked = False
            for i in range(len(park_switch)):
                if park_switch[i].name == "PARK" and park_switch[i].s == PyIndi.ISS_ON:
                    is_parked = True
                    break

            if is_parked:
                clientlogger.info("Mount is parked, unparking...")
                if not self.set_switch(device, "TELESCOPE_PARK", "UNPARK"):
                    clientlogger.error("Failed to unpark mount")
                    return False
                clientlogger.info("Mount unparked successfully")
            else:
                clientlogger.debug("Mount is not parked")

            return True

        except Exception as e:
            clientlogger.exception(f"Error unparking mount: {e}")
            return False

    def enable_sidereal_tracking(self, device) -> bool:
        """Enable sidereal tracking on the mount.

        Args:
            device: The INDI telescope device

        Returns:
            True if tracking was enabled successfully, False on error.
        """
        try:
            # Set tracking mode to sidereal
            track_mode_prop = self._wait_for_property(device, "TELESCOPE_TRACK_MODE", timeout=2.0)
            if track_mode_prop:
                if not self.set_switch(device, "TELESCOPE_TRACK_MODE", "TRACK_SIDEREAL"):
                    clientlogger.warning("Failed to set tracking mode to sidereal")
                else:
                    clientlogger.info("Tracking mode set to sidereal")
            else:
                clientlogger.debug("TELESCOPE_TRACK_MODE property not available, will use default tracking mode")

            # Enable tracking
            track_state_prop = self._wait_for_property(device, "TELESCOPE_TRACK_STATE", timeout=2.0)
            if track_state_prop:
                if not self.set_switch(device, "TELESCOPE_TRACK_STATE", "TRACK_ON"):
                    clientlogger.error("Failed to enable tracking")
                    return False
                clientlogger.info("Tracking enabled")
            else:
                clientlogger.warning("TELESCOPE_TRACK_STATE property not available")
                return False

            return True

        except Exception as e:
            clientlogger.exception(f"Error enabling sidereal tracking: {e}")
            return False

    def newDevice(self, device):
        """Called when a new device is detected by the INDI server."""
        device_name = device.getDeviceName().lower()
        # Match telescope/mount devices, but exclude CCD and Focuser simulators
        if self.telescope_device is None:
            if (
                any(
                    keyword in device_name
                    for keyword in ["telescope", "mount", "eqmod", "lx200"]
                )
                or device_name == "telescope simulator"
            ):
                self.telescope_device = device
                clientlogger.info(
                    f"Telescope device detected: {device.getDeviceName()}"
                )

    def removeDevice(self, device):
        """Called when a device is removed from the INDI server."""
        if (
            self.telescope_device
            and device.getDeviceName() == self.telescope_device.getDeviceName()
        ):
            clientlogger.warning(f"Telescope device removed: {device.getDeviceName()}")
            self.telescope_device = None

    def newProperty(self, property):
        """Called when a new property is created for a device."""
        clientlogger.debug(
            f"New property: {property.getName()} on device {property.getDeviceName()}"
        )

    def removeProperty(self, property):
        """Called when a property is deleted from a device."""
        clientlogger.debug(
            f"Property removed: {property.getName()} on device {property.getDeviceName()}"
        )

    def newBLOB(self, bp):
        """Handle new BLOB property updates (not used for mount control)."""
        pass

    def newSwitch(self, svp):
        """Handle new switch property value updates."""
        # Monitor TELESCOPE_MOTION_* for tracking state changes
        pass

    def newNumber(self, nvp):
        """Handle new number property value updates.

        This is called when numeric properties change, including:
        - EQUATORIAL_EOD_COORD or EQUATORIAL_COORD: Current RA/Dec position
        - Target position updates
        """
        clientlogger.debug(
            f"New number property: {nvp.getName()} on device {nvp.getDeviceName()}"
        )
        if nvp.name == "EQUATORIAL_EOD_COORD":
            # Position update - extract RA and Dec
            ra_hours = None
            dec_deg = None

            for widget in nvp:
                if widget.name == "RA":
                    ra_hours = widget.value
                elif widget.name == "DEC":
                    dec_deg = widget.value

            if ra_hours is not None and dec_deg is not None:
                ra_deg = ra_hours * 15.0  # Convert hours to degrees
                self.mount_control._mount_current_position(ra_deg, dec_deg)

    def newText(self, tvp):
        """Handle new text property value updates."""
        pass

    def newLight(self, lvp):
        """Handle new light property value updates."""
        pass

    def newMessage(self, device, message):
        """Handle messages from INDI devices."""
        clientlogger.info(
            f"INDI message from {device.getDeviceName()}: {device.messageQueue(message)}"
        )

    def serverConnected(self):
        """Called when successfully connected to INDI server."""
        clientlogger.info("Connected to INDI server.")

    def serverDisconnected(self, code):
        """Called when disconnected from INDI server."""
        clientlogger.warning(f"Disconnected from INDI server with code {code}.")

    def updateProperty(self, property):
        """Called when a property is updated."""
        if property.getDeviceName() != (
            self.telescope_device.getDeviceName() if self.telescope_device else None
        ):
            if property.getName() not in ["MOUNT_AXES", "TARGET_EOD_COORD"]:
                clientlogger.debug(
                    f"Property updated: {property.getName()} on device {property.getDeviceName()} of type {property.getType()}"
                )
        nvp = PyIndi.PropertyNumber(property)
        if nvp.isValid():
            if "MOUNT_AXES" == nvp.getName():
                for widget in nvp:
                    if widget.name == "PRIMARY":
                        self._axis_primary = widget.value
                    elif widget.name == "SECONDARY":
                        self._axis_secondary = widget.value
            elif "EQUATORIAL_EOD_COORD" == nvp.getName():
                current_ra = None
                current_dec = None
                for widget in nvp:
                    if widget.name == "RA":
                        current_ra = widget.value * 15.0  # Convert hours to degrees
                    elif widget.name == "DEC":
                        current_dec = widget.value
                if current_ra is not None and current_dec is not None:
                    clientlogger.debug(
                        f"Current position updated: RA={current_ra:.4f}°, Dec={current_dec:.4f}°"
                    )
                    self.mount_control._mount_current_position(current_ra, current_dec)


class MountControlIndi(MountControlBase):
    """INDI-based telescope mount control implementation.

    This class implements the MountControlBase interface using the INDI protocol
    to communicate with telescope mounts. It connects to a local or remote INDI
    server and controls any INDI-compatible mount.

    Args:
        mount_queue: Queue for receiving mount commands
        console_queue: Queue for sending status messages to UI
        shared_state: Shared state object for inter-process communication
        log_queue: Queue for logging messages
        indi_host: INDI server hostname (default: "localhost")
        indi_port: INDI server port (default: 7624)
    """

    def __init__(
        self,
        mount_queue: Queue,
        console_queue: Queue,
        shared_state: SharedStateObj,
        log_queue: Queue,
        indi_host: str = "localhost",
        indi_port: int = 7624,
        target_tolerance_deg: float = 0.01,
    ):
        super().__init__(mount_queue, console_queue, shared_state)

        self.indi_host = indi_host
        self.indi_port = indi_port

        # Create INDI client
        self.client = PiFinderIndiClient(self)
        self.client.setServer(self.indi_host, self.indi_port)

        # Connection will be established in init_mount()
        self._telescope = None

        self.current_ra: Optional[float] = None
        self.current_dec: Optional[float] = None
        self.current_time: float = 0.0  # Timestamp of last position update
        self._current_position_update_threshold = 1.5  # seconds

        self._target_ra: Optional[float] = None
        self._target_dec: Optional[float] = None
        self._target_tolerance_deg = target_tolerance_deg

        # Available slew rates (will be populated during init_mount)
        self.available_slew_rates: List[str] = []

        self.log_queue = log_queue

    def _get_telescope_device(self):
        """Get the telescope device from the INDI client.

        Returns:
            The telescope device if available, None otherwise.
        """
        return self.client.telescope_device

    def _mount_current_position(self, ra_deg: float, dec_deg: float) -> None:
        """Update the current position of the mount.

        Args:
            ra_deg: Right Ascension in degrees
            dec_deg: Declination in degrees
        """
        self.current_ra = ra_deg
        self.current_dec = dec_deg
        self.current_time = time.time()
        self.mount_current_position(ra_deg, dec_deg)
        if self._check_target_reached():
            logger.info(
                f"Target reached: RA={self.current_ra:.4f}°, Dec={self.current_dec:.4f}° "
                f"(target was RA={self._target_ra:.4f}°, Dec={self._target_dec:.4f}°)"
            )
            # Need these for retries in REFINE phase
            # self._target_ra = None
            # self._target_dec = None

            # Avoid is_mount_moving() returning True immediately after target reached
            # There should be no more updates coming.
            self.current_time = (
                self.current_time - self._current_position_update_threshold - 1.0
            )
            self.mount_target_reached()

    def _radec_diff(
        self, ra1: float, dec1: float, ra2: float, dec2: float
    ) -> Tuple[float, float]:
        """Calculate the difference between two RA/Dec positions in degrees.

        Args:
            ra1: First RA in degrees
            dec1: First Dec in degrees
            ra2: Second RA in degrees
            dec2: Second Dec in degrees
        Returns:
            Tuple of (delta_ra, delta_dec) in degrees
        """
        # Calculate RA difference accounting for wrap-around at 360°
        ra_diff = ra2 - ra1
        if ra_diff > 180:
            ra_diff -= 360
        elif ra_diff < -180:
            ra_diff += 360
        dec_diff = dec2 - dec1  # Dec -90 .. +90, no wrap-around
        return (ra_diff, dec_diff)

    def _check_target_reached(self) -> bool:
        """Check if the current position matches the target position within tolerance."""

        if (
            self._target_ra is None
            or self._target_dec is None
            or self.current_ra is None
            or self.current_dec is None
        ):
            return False

        ra_diff, dec_diff = self._radec_diff(
            self.current_ra, self.current_dec, self._target_ra, self._target_dec
        )

        # Check if within tolerance
        return (
            abs(ra_diff) <= self._target_tolerance_deg
            and abs(dec_diff) <= self._target_tolerance_deg
        )

    # Implementation of abstract methods from MountControlBase

    def init_mount(
        self,
        latitude_deg: Optional[float] = None,
        longitude_deg: Optional[float] = None,
        elevation_m: Optional[float] = None,
        utc_time: Optional[str] = None,
        solve_ra_deg: Optional[float] = None,
        solve_dec_deg: Optional[float] = None,
    ) -> bool:
        """Initialize connection to the INDI mount.

        Args:
            latitude_deg: Observatory latitude in degrees (positive North). Optional.
            longitude_deg: Observatory longitude in degrees (positive East). Optional.
            elevation_m: Observatory elevation in meters above sea level. Optional.
            utc_time: UTC time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS). Optional.
            solve_ra_deg: Solved Right Ascension in degrees for initial sync. Optional.
            solve_dec_deg: Solved Declination in degrees for initial sync. Optional.

        Returns:
            True if initialization successful, False otherwise.
        """
        logger.debug("Initializing mount: connect, unpark, set location/time")
        if solve_ra_deg is not None and solve_dec_deg is not None:
            logger.debug(
                f"Will sync mount to solved position: RA={solve_ra_deg:.4f}°, Dec={solve_dec_deg:.4f}°"
            )
        try:
            if self.client.isServerConnected():
                logger.debug("init_mount: Already connected to INDI server")
            else:
                if not self.client.connectServer():
                    logger.error(
                        f"Failed to connect to INDI server at {self.indi_host}:{self.indi_port}"
                    )
                    return False

                logger.info(
                    f"Connected to INDI server at {self.indi_host}:{self.indi_port}"
                )

                # Wait for telescope device to be detected
                timeout = 5.0
                start_time = time.time()
                while time.time() - start_time < timeout:
                    if self._get_telescope_device():
                        break
                    time.sleep(0.1)

                if not self._get_telescope_device():
                    logger.error("No telescope device detected")
                    return False

                logger.info(
                    f"Telescope device found: {self._get_telescope_device().getDeviceName()}"
                )

            # Connect to the telescope device if not already connected
            device = self._get_telescope_device()
            device_name = device.getDeviceName()

            # Check CONNECTION property
            if self.client._wait_for_property(device, "CONNECTION"):
                connect_prop = device.getSwitch("CONNECTION")
                if connect_prop:
                    # Check if already connected
                    for i in range(len(connect_prop)):
                        if (
                            connect_prop[i].name == "CONNECT"
                            and connect_prop[i].s == PyIndi.ISS_ON
                        ):
                            logger.info(f"Telescope {device_name} already connected")
                            return True

                    # Connect the device
                    if not self.client.set_switch(device, "CONNECTION", "CONNECT"):
                        logger.error(
                            f"Failed to connect telescope device {device_name}"
                        )
                        return False

                    # Wait for connection to establish
                    time.sleep(1.0)
                    logger.info(f"Telescope {device_name} connected successfully")

            # Set geographic coordinates if provided
            if latitude_deg is not None and longitude_deg is not None:
                values = {"LAT": latitude_deg, "LONG": longitude_deg}
                if elevation_m is not None:
                    values["ELEV"] = elevation_m

                if self.client.set_number(device, "GEOGRAPHIC_COORD", values):
                    logger.info(
                        f"Geographic coordinates set: Lat={latitude_deg}°, Lon={longitude_deg}°, Elev={elevation_m}m"
                    )
                else:
                    logger.warning("Failed to set geographic coordinates")

            # Set UTC time if provided
            if utc_time is not None:
                # Parse ISO 8601 format: YYYY-MM-DDTHH:MM:SS
                try:
                    import datetime

                    dt = datetime.datetime.fromisoformat(utc_time)

                    # Calculate UTC offset in hours (0 for UTC)
                    utc_offset = 0

                    # TIME_UTC is a text property with format: UTC="YYYY-MM-DDTHH:MM:SS" and OFFSET="hours"
                    utc_values = {"UTC": dt.isoformat(), "OFFSET": str(utc_offset)}

                    if self.client.set_text(device, "TIME_UTC", utc_values):
                        logger.info(f"UTC time set: {utc_time}")
                    else:
                        logger.warning("Failed to set UTC time")
                except (ValueError, AttributeError) as e:
                    logger.error(f"Invalid UTC time format '{utc_time}': {e}")

            # Read available slew rates from TELESCOPE_SLEW_RATE property
            slew_rate_prop = self.client._wait_for_property(
                device, "TELESCOPE_SLEW_RATE", timeout=2.0
            )
            if slew_rate_prop:
                slew_rate_switch = device.getSwitch("TELESCOPE_SLEW_RATE")
                if slew_rate_switch:
                    self.available_slew_rates = []
                    for widget in slew_rate_switch:
                        self.available_slew_rates.append(widget.name)
                    logger.info(
                        f"Available slew rates: {', '.join(self.available_slew_rates)}"
                    )
                else:
                    logger.warning("Could not get TELESCOPE_SLEW_RATE switch property")
            else:
                logger.warning(
                    "TELESCOPE_SLEW_RATE property not available on this mount"
                )

            # Unpark mount if parked
            if not self.client.unpark_mount(device):
                logger.warning("Failed to unpark mount, continuing anyway")

            # Set mount to sidereal tracking
            if not self.client.enable_sidereal_tracking(device):
                logger.warning("Failed to enable sidereal tracking, continuing anyway")

            # Sync mount if solve coordinates provided
            if solve_ra_deg is not None and solve_dec_deg is not None:
                logger.info(
                    f"Syncing mount to solved position: RA={solve_ra_deg:.4f}°, Dec={solve_dec_deg:.4f}°"
                )
                if not self.sync_mount(solve_ra_deg, solve_dec_deg):
                    logger.warning("Failed to sync mount to solved position during initialization")
                    # Don't fail initialization if sync fails
                else:
                    logger.info("Mount successfully synced to solved position")

            return True

        except Exception as e:
            logger.exception(f"Error initializing mount: {e}")
            return False

    def sync_mount(
        self, current_position_ra_deg: float, current_position_dec_deg: float
    ) -> bool:
        """Sync the mount to the specified position.

        Activates tracking after coordinates are set as next command and activates tracking.

        Args:
            current_position_ra_deg: Current RA in degrees
            current_position_dec_deg: Current Dec in degrees

        Returns:
            True if sync successful, False otherwise.
        """
        logger.debug(
            f"Syncing mount to RA={current_position_ra_deg:.4f}°, Dec={current_position_dec_deg:.4f}°"
        )
        try:
            device = self._get_telescope_device()
            if not device:
                logger.error("Telescope device not available for sync")
                return False

            # First set ON_COORD_SET to SYNC mode
            if not self.client.set_switch(device, "ON_COORD_SET", "SYNC"):
                logger.error("Failed to set ON_COORD_SET to SYNC")
                return False

            # Convert RA from degrees to hours
            ra_hours = current_position_ra_deg / 15.0

            # Set target coordinates
            if not self.client.set_number(
                device,
                "EQUATORIAL_EOD_COORD",
                {"RA": ra_hours, "DEC": current_position_dec_deg},
            ):
                logger.error("Failed to set sync coordinates")
                return False

            if not self.client.set_switch(device, "ON_COORD_SET", "TRACK"):
                logger.error("Failed to set ON_COORD_SET to TRACK (after sync)")
                return False

            if not self.client.set_switch(device, "TELESCOPE_TRACK_STATE", "TRACK_ON"):
                logger.error("Failed to set telescope to tracking")
                return False

            logger.info(
                f"Mount synced to RA={current_position_ra_deg:.4f}°, Dec={current_position_dec_deg:.4f}°"
            )
            self.current_ra = current_position_ra_deg
            self.current_dec = current_position_dec_deg
            # Need these for retries in REFINE phase
            # self._target_dec = None
            # self._target_ra = None
            return True

        except Exception as e:
            logger.exception(f"Error syncing mount: {e}")
            return False

    def stop_mount(self) -> bool:
        """Stop any current movement of the mount.

        Returns:
            True if stop command sent successfully, False otherwise.
        """
        try:
            device = self._get_telescope_device()
            if not device:
                logger.error("Telescope device not available for stop")
                return False

            # Send TELESCOPE_ABORT_MOTION command
            if not self.client.set_switch(device, "TELESCOPE_ABORT_MOTION", "ABORT"):
                logger.error("Failed to send abort motion command")
                return False

            logger.info("Mount stop command sent")

            # Notify base class that mount has stopped
            self.mount_stopped()
            return True

        except Exception as e:
            logger.exception(f"Error stopping mount: {e}")
            return False

    def move_mount_to_target(self, target_ra_deg: float, target_dec_deg: float) -> bool:
        """Move the mount to the specified target position.

        Args:
            target_ra_deg: Target RA in degrees
            target_dec_deg: Target Dec in degrees

        Returns:
            True if goto command sent successfully, False otherwise.
        """
        try:
            device = self._get_telescope_device()
            if not device:
                logger.error("Telescope device not available for goto")
                return False

            # Set ON_COORD_SET to TRACK mode (goto and track)
            if not self.client.set_switch(device, "ON_COORD_SET", "TRACK"):
                logger.error("Failed to set ON_COORD_SET to TRACK")
                return False

            # Convert RA from degrees to hours
            ra_hours = target_ra_deg / 15.0

            # Set target coordinates
            if not self.client.set_number(
                device, "EQUATORIAL_EOD_COORD", {"RA": ra_hours, "DEC": target_dec_deg}
            ):
                logger.error("Failed to set goto coordinates")
                return False

            logger.info(
                f"Mount commanded to goto RA={target_ra_deg:.4f}°, Dec={target_dec_deg:.4f}°"
            )
            self._target_ra = target_ra_deg
            self._target_dec = target_dec_deg
            self.current_time = time.time()  # Update timestamp to indicate movement

            return True

        except Exception as e:
            logger.exception(f"Error commanding mount to target: {e}")
            return False

    def is_mount_moving(self) -> bool:
        # Assume moutn is moving if last position update was recently
        return time.time() - self.current_time < self._current_position_update_threshold

    def set_mount_drift_rates(
        self, drift_rate_ra: float, drift_rate_dec: float
    ) -> bool:
        """Set the mount's drift compensation rates.

        Args:
            drift_rate_ra: Drift rate in RA (arcsec/sec)
            drift_rate_dec: Drift rate in Dec (arcsec/sec)

        Returns:
            True if drift rates set successfully, False otherwise.
        """
        # Not all INDI drivers support drift rates
        # This would require TELESCOPE_TRACK_RATE property
        logger.warning("Drift rate control not yet implemented for INDI")
        return False

    def move_mount_manual(
        self, direction: MountDirections, slew_rate: str, duration: float
    ) -> bool:
        """Move the mount manually in the specified direction.

        Args:
            direction: Direction to move (MountDirectionsEquatorial or MountDirectionsAltAz)
            step_deg: Step size in degrees

        Returns:
            True if manual movement command sent successfully, False otherwise.
        """
        try:
            device = self._get_telescope_device()
            if not device:
                logger.error("Telescope device not available for manual movement")
                return False

            if self.current_ra is None or self.current_dec is None:
                logger.error("Current mount position unknown, cannot move manually")
                self.console_queue.put(
                    {"WARN", "Mount position unknown, cannot move manually"}
                )
                return False

            # Map direction to INDI motion commands
            motion_map = {
                MountDirectionsEquatorial.NORTH: (
                    "TELESCOPE_MOTION_NS",
                    "MOTION_NORTH",
                ),
                MountDirectionsEquatorial.SOUTH: (
                    "TELESCOPE_MOTION_NS",
                    "MOTION_SOUTH",
                ),
                MountDirectionsEquatorial.EAST: ("TELESCOPE_MOTION_WE", "MOTION_EAST"),
                MountDirectionsEquatorial.WEST: ("TELESCOPE_MOTION_WE", "MOTION_WEST"),
                MountDirectionsAltAz.UP: ("TELESCOPE_MOTION_NS", "MOTION_NORTH"),
                MountDirectionsAltAz.DOWN: ("TELESCOPE_MOTION_NS", "MOTION_SOUTH"),
                MountDirectionsAltAz.LEFT: ("TELESCOPE_MOTION_WE", "MOTION_WEST"),
                MountDirectionsAltAz.RIGHT: ("TELESCOPE_MOTION_WE", "MOTION_EAST"),
            }

            if direction not in motion_map:
                logger.error(f"Unknown direction: {direction}")
                return False

            property_name, element_name = motion_map[direction]

            # For manual movement with a specific step size, we'd ideally use
            # timed pulses or jog commands. For simplicity, we'll use motion on/off.
            # A better implementation would calculate timing based on step_deg.

            (prev_ra, prev_dec) = (self.current_ra, self.current_dec)
            logger.info(
                f"START manual movement {direction} by {slew_rate} at RA={prev_ra:.7f}, Dec={prev_dec:.7f}"
            )

            # Set slew rate based on passed velocity
            if slew_rate in self.available_slew_rates:
                if not self.client.set_switch(device, "TELESCOPE_SLEW_RATE", slew_rate):
                    logger.warning(f"Failed to set slew rate to {slew_rate}")
            else:
                logger.warning(
                    f"Unknown slew rate setting: {slew_rate} (not in available rates: {self.available_slew_rates})"
                )
                return False

            # Turn on motion
            if not self.client.set_switch(device, property_name, element_name):
                logger.error(f"Failed to start manual movement {direction}")
                return False

            self.current_time = time.time()  # Update timestamp to indicate movement
            # Wait for the passed duration
            time.sleep(duration)

            # Turn off motion by setting all switches to OFF
            if not self.client.set_switch_off(device, property_name):
                logger.warning(f"Failed to stop motion for {property_name}")

            return True

        except Exception as e:
            logger.exception(f"Error in manual movement: {e}")
            return False

    def disconnect_mount(self) -> bool:
        """Disconnect from the INDI mount.

        Returns:
            True if disconnection successful, False otherwise.
        """
        try:
            device = self._get_telescope_device()
            if device:
                self.client.set_switch(device, "CONNECTION", "DISCONNECT")
                logger.info(f"Telescope {device.getDeviceName()} disconnected")

            if self.client.isServerConnected():
                self.client.disconnectServer()
                logger.info("Disconnected from INDI server")

            return True

        except Exception as e:
            logger.exception(f"Error disconnecting mount: {e}")
            return False


def run(
    mount_queue: Queue,
    console_queue: Queue,
    shared_state: SharedStateObj,
    log_queue: Queue,
    indi_host: str = "localhost",
    indi_port: int = 7624,
):
    """Run the INDI mount control process.

    Args:
        mount_queue: Queue for receiving mount commands
        console_queue: Queue for sending status messages
        shared_state: Shared state object
        log_queue: Queue for logging
        indi_host: INDI server hostname
        indi_port: INDI server port
    """
    if log_queue is not None:
        MultiprocLogging.configurer(log_queue)
    mount_control = MountControlIndi(
        mount_queue, console_queue, shared_state, log_queue, indi_host, indi_port
    )
    try:
        mount_control.run()
    except KeyboardInterrupt:
        logger.info("Shutting down MountControlIndi.")
        raise
