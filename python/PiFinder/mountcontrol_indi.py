from PiFinder.mountcontrol_interface import MountControlBase, MountDirections, MountDirectionsEquatorial, MountDirectionsAltAz
import PyIndi
import logging
import time

from PiFinder.multiproclogging import MultiprocLogging

logger = logging.getLogger("IndiMountControl")

#
# source .venv/bin/activate && pip uninstall -y pyindi-client && pip install --no-binary :all: pyindi-client
#
class PiFinderIndiClient(PyIndi.BaseClient):
    """INDI client for PiFinder telescope mount control.

    This client connects to an INDI server and manages communication with
    telescope/mount devices. It automatically detects telescope devices and
    monitors their properties for position updates and movement status.
    """
    def __init__(self, mount_control):
        super().__init__()
        self.telescope_device = None
        self.mount_control = mount_control
        self._last_ra = None
        self._last_dec = None
        self._target_ra = None
        self._target_dec = None
        self._target_callback = None
        self._target_tolerance_deg = 0.1  # Tolerance in degrees to consider target reached

    def newDevice(self, device):
        """Called when a new device is detected by the INDI server."""
        device_name = device.getDeviceName().lower()
        # Match telescope/mount devices, but exclude CCD and Focuser simulators
        if self.telescope_device is None:
            if (any(keyword in device_name for keyword in ["telescope", "mount", "eqmod", "lx200"]) or
                device_name == "telescope simulator"):
                self.telescope_device = device
                logger.info(f"Telescope device detected: {device.getDeviceName()}")

    def removeDevice(self, device):
        """Called when a device is removed from the INDI server."""
        if self.telescope_device and device.getDeviceName() == self.telescope_device.getDeviceName():
            logger.warning(f"Telescope device removed: {device.getDeviceName()}")
            self.telescope_device = None

    def newProperty(self, property):
        """Called when a new property is created for a device."""
        logger.debug(f"New property: {property.getName()} on device {property.getDeviceName()}")

    def removeProperty(self, property):
        """Called when a property is deleted from a device."""
        logger.debug(f"Property removed: {property.getName()} on device {property.getDeviceName()}")

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
        if nvp.name == "EQUATORIAL_EOD_COORD" or nvp.name == "EQUATORIAL_COORD":
            # Position update - extract RA and Dec
            ra_hours = None
            dec_deg = None

            for i in range(len(nvp)):
                elem = nvp[i]
                if elem.name == "RA":
                    ra_hours = elem.value
                elif elem.name == "DEC":
                    dec_deg = elem.value

            if ra_hours is not None and dec_deg is not None:
                ra_deg = ra_hours * 15.0  # Convert hours to degrees
                # Only notify if position changed significantly (avoid spam)
                if self._last_ra is None or self._last_dec is None or \
                   abs(ra_deg - self._last_ra) > 0.001 or abs(dec_deg - self._last_dec) > 0.001:
                    self._last_ra = ra_deg
                    self._last_dec = dec_deg
                    self.mount_control.mount_current_position(ra_deg, dec_deg)
                    logger.debug(f"Position update: RA={ra_deg:.4f}°, Dec={dec_deg:.4f}°")
                    # Check if we've reached the target
                    self._check_target_reached()

    def newText(self, tvp):
        """Handle new text property value updates."""
        pass

    def newLight(self, lvp):
        """Handle new light property value updates."""
        pass

    def newMessage(self, device, message):
        """Handle messages from INDI devices."""
        logger.info(f"INDI message from {device.getDeviceName()}: {message}")

    def serverConnected(self):
        """Called when successfully connected to INDI server."""
        logger.info("Connected to INDI server.")

    def serverDisconnected(self, code):
        """Called when disconnected from INDI server."""
        logger.warning(f"Disconnected from INDI server with code {code}.")

    def setCallbackForTarget(self, target_ra_deg: float, target_dec_deg: float, callback):
        """Set a callback to be called when the mount reaches the target position.

        Args:
            target_ra_deg: Target RA in degrees
            target_dec_deg: Target Dec in degrees
            callback: Function to call when target is reached (no arguments)
        """
        self._target_ra = target_ra_deg
        self._target_dec = target_dec_deg
        self._target_callback = callback
        logger.debug(f"Target callback set for RA={target_ra_deg:.4f}°, Dec={target_dec_deg:.4f}°")

    def _check_target_reached(self):
        """Check if the current position matches the target position within tolerance."""
        if self._target_callback is None:
            return  # No active target callback

        if self._last_ra is None or self._last_dec is None:
            return  # Don't have current position yet

        if self._target_ra is None or self._target_dec is None:
            return  # No target set

        # Calculate distance from target
        ra_diff = abs(self._last_ra - self._target_ra)
        dec_diff = abs(self._last_dec - self._target_dec)

        # Check if within tolerance
        if ra_diff <= self._target_tolerance_deg and dec_diff <= self._target_tolerance_deg:
            logger.info(f"Target reached: RA={self._last_ra:.4f}°, Dec={self._last_dec:.4f}° "
                       f"(target was RA={self._target_ra:.4f}°, Dec={self._target_dec:.4f}°)")
            # Call the callback and clear it
            callback = self._target_callback
            self._target_callback = None
            self._target_ra = None
            self._target_dec = None
            callback()


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

    def __init__(self, mount_queue, console_queue, shared_state, log_queue,
                 indi_host="localhost", indi_port=7624):
        super().__init__(mount_queue, console_queue, shared_state, log_queue)

        self.indi_host = indi_host
        self.indi_port = indi_port

        # Create INDI client
        self.client = PiFinderIndiClient(self)
        self.client.setServer(self.indi_host, self.indi_port)

        # Connection will be established in init_mount()
        self._connected = False
        self._telescope = None

    def _get_telescope_device(self):
        """Get the telescope device from the INDI client.

        Returns:
            The telescope device if available, None otherwise.
        """
        return self.client.telescope_device

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
        return None

    def _set_switch(self, device_name, property_name, element_name, timeout=5.0):
        """Set a switch property to ON.

        Args:
            device_name: Name of the INDI device
            property_name: Name of the switch property
            element_name: Name of the switch element to turn ON
            timeout: Maximum time to wait for property

        Returns:
            True if successful, False otherwise.
        """
        device = self._get_telescope_device()
        if not device:
            logger.error(f"Device {device_name} not available")
            return False

        # Wait for property to be available, then get as properly typed switch
        if not self._wait_for_property(device, property_name, timeout):
            logger.error(f"Property {property_name} not available on {device_name}")
            return False

        switch_prop = device.getSwitch(property_name)
        if not switch_prop:
            logger.error(f"Could not get switch property {property_name} on {device_name}")
            return False

        # Find and activate the switch
        for i in range(len(switch_prop)):
            switch = switch_prop[i]
            if switch.name == element_name:
                switch.s = PyIndi.ISS_ON
            else:
                switch.s = PyIndi.ISS_OFF

        self.client.sendNewSwitch(switch_prop)
        return True

    def _set_number(self, device_name, property_name, values, timeout=5.0):
        """Set numeric property values.

        Args:
            device_name: Name of the INDI device
            property_name: Name of the numeric property
            values: Dictionary mapping element names to values
            timeout: Maximum time to wait for property

        Returns:
            True if successful, False otherwise.
        """
        device = self._get_telescope_device()
        if not device:
            logger.error(f"Device {device_name} not available")
            return False

        # Wait for property to be available, then get as properly typed number property
        if not self._wait_for_property(device, property_name, timeout):
            logger.error(f"Property {property_name} not available on {device_name}")
            return False

        num_prop = device.getNumber(property_name)
        if not num_prop:
            logger.error(f"Could not get number property {property_name} on {device_name}")
            return False

        # Set the values
        for i in range(len(num_prop)):
            num = num_prop[i]
            if num.name in values:
                num.value = values[num.name]

        self.client.sendNewNumber(num_prop)
        return True

    # Implementation of abstract methods from MountControlBase

    def init_mount(self, latitude_deg: float = None, longitude_deg: float = None,
                   elevation_m: float = None, utc_time: str = None) -> bool:
        """Initialize connection to the INDI mount.

        Args:
            latitude_deg: Observatory latitude in degrees (positive North). Optional.
            longitude_deg: Observatory longitude in degrees (positive East). Optional.
            elevation_m: Observatory elevation in meters above sea level. Optional.
            utc_time: UTC time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS). Optional.

        Returns:
            True if initialization successful, False otherwise.
        """
        try:
            if not self._connected:
                if not self.client.connectServer():
                    logger.error(f"Failed to connect to INDI server at {self.indi_host}:{self.indi_port}")
                    return False

                self._connected = True
                logger.info(f"Connected to INDI server at {self.indi_host}:{self.indi_port}")

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

                logger.info(f"Telescope device found: {self._get_telescope_device().getDeviceName()}")

            # Connect to the telescope device if not already connected
            device = self._get_telescope_device()
            device_name = device.getDeviceName()

            # Check CONNECTION property
            if self._wait_for_property(device, "CONNECTION"):
                connect_prop = device.getSwitch("CONNECTION")
                if connect_prop:
                    # Check if already connected
                    for i in range(len(connect_prop)):
                        if connect_prop[i].name == "CONNECT" and connect_prop[i].s == PyIndi.ISS_ON:
                            logger.info(f"Telescope {device_name} already connected")
                            return True

                    # Connect the device
                    if not self._set_switch(device_name, "CONNECTION", "CONNECT"):
                        logger.error(f"Failed to connect telescope device {device_name}")
                        return False

                    # Wait for connection to establish
                    time.sleep(1.0)
                    logger.info(f"Telescope {device_name} connected successfully")

            # Set geographic coordinates if provided
            if latitude_deg is not None and longitude_deg is not None:
                values = {"LAT": latitude_deg, "LONG": longitude_deg}
                if elevation_m is not None:
                    values["ELEV"] = elevation_m

                if self._set_number(device_name, "GEOGRAPHIC_COORD", values):
                    logger.info(f"Geographic coordinates set: Lat={latitude_deg}°, Lon={longitude_deg}°, Elev={elevation_m}m")
                else:
                    logger.warning("Failed to set geographic coordinates")

            # Set UTC time if provided
            if utc_time is not None:
                # Parse ISO 8601 format: YYYY-MM-DDTHH:MM:SS
                try:
                    import datetime
                    dt = datetime.datetime.fromisoformat(utc_time)

                    # INDI expects separate date and time values
                    utc_values = {
                        "UTC": f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}",
                        "OFFSET": "0"  # UTC offset is 0
                    }

                    # Some drivers may want UTC_TIME instead
                    if self._set_number(device_name, "TIME_UTC", utc_values):
                        logger.info(f"UTC time set: {utc_time}")
                    else:
                        logger.warning("Failed to set UTC time")
                except (ValueError, AttributeError) as e:
                    logger.error(f"Invalid UTC time format '{utc_time}': {e}")

            return True

        except Exception as e:
            logger.exception(f"Error initializing mount: {e}")
            return False

    def sync_mount(self, current_position_ra_deg: float, current_position_dec_deg: float) -> bool:
        """Sync the mount to the specified position.

        Args:
            current_position_ra_deg: Current RA in degrees
            current_position_dec_deg: Current Dec in degrees

        Returns:
            True if sync successful, False otherwise.
        """
        try:
            device = self._get_telescope_device()
            if not device:
                logger.error("Telescope device not available for sync")
                return False

            device_name = device.getDeviceName()

            # First set ON_COORD_SET to SYNC mode
            if not self._set_switch(device_name, "ON_COORD_SET", "SYNC"):
                logger.error("Failed to set ON_COORD_SET to SYNC")
                return False

            # Convert RA from degrees to hours
            ra_hours = current_position_ra_deg / 15.0

            # Set target coordinates
            if not self._set_number(device_name, "EQUATORIAL_EOD_COORD",
                                   {"RA": ra_hours, "DEC": current_position_dec_deg}):
                logger.error("Failed to set sync coordinates")
                return False

            logger.info(f"Mount synced to RA={current_position_ra_deg:.4f}°, Dec={current_position_dec_deg:.4f}°")
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

            device_name = device.getDeviceName()

            # Send TELESCOPE_ABORT_MOTION command
            if not self._set_switch(device_name, "TELESCOPE_ABORT_MOTION", "ABORT"):
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

            device_name = device.getDeviceName()

            # Set ON_COORD_SET to TRACK mode (goto and track)
            if not self._set_switch(device_name, "ON_COORD_SET", "TRACK"):
                logger.error("Failed to set ON_COORD_SET to TRACK")
                return False

            # Convert RA from degrees to hours
            ra_hours = target_ra_deg / 15.0

            # Set target coordinates
            if not self._set_number(device_name, "EQUATORIAL_EOD_COORD",
                                   {"RA": ra_hours, "DEC": target_dec_deg}):
                logger.error("Failed to set goto coordinates")
                return False

            logger.info(f"Mount commanded to goto RA={target_ra_deg:.4f}°, Dec={target_dec_deg:.4f}°")

            self.client.setCallbackForTarget(target_ra_deg, target_dec_deg, self.mount_target_reached)
            
            return True

        except Exception as e:
            logger.exception(f"Error commanding mount to target: {e}")
            return False

    def set_mount_drift_rates(self, drift_rate_ra: float, drift_rate_dec: float) -> bool:
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

    def move_mount_manual(self, direction: MountDirections, step_deg: float) -> bool:
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

            device_name = device.getDeviceName()

            # Map direction to INDI motion commands
            motion_map = {
                MountDirectionsEquatorial.NORTH: ("TELESCOPE_MOTION_NS", "MOTION_NORTH"),
                MountDirectionsEquatorial.SOUTH: ("TELESCOPE_MOTION_NS", "MOTION_SOUTH"),
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

            # Turn on motion
            if not self._set_switch(device_name, property_name, element_name):
                logger.error(f"Failed to start manual movement {direction}")
                return False

            # Calculate duration based on step size (rough estimate)
            # Assume 1 degree/second slew rate for manual movements
            duration = step_deg

            # Wait for the calculated duration
            time.sleep(duration)

            # Turn off motion by setting all switches to OFF
            device = self._get_telescope_device()
            motion_prop = device.getSwitch(property_name)
            if motion_prop:
                for i in range(len(motion_prop)):
                    motion_prop[i].s = PyIndi.ISS_OFF
                self.client.sendNewSwitch(motion_prop)

            logger.info(f"Manual movement {direction} by {step_deg}° completed")
            return True

        except Exception as e:
            logger.exception(f"Error in manual movement: {e}")
            return False

    def set_mount_step_size(self, step_size_deg: float) -> bool:
        """Set the mount's step size for manual movements.

        Args:
            step_size_deg: Step size in degrees

        Returns:
            True if step size set successfully, False otherwise.
        """
        # Step size is managed by the base class, not the mount
        # So we just return True
        logger.debug(f"Step size set to {step_size_deg}°")
        return True

    def disconnect_mount(self) -> bool:
        """Disconnect from the INDI mount.

        Returns:
            True if disconnection successful, False otherwise.
        """
        try:
            device = self._get_telescope_device()
            if device:
                device_name = device.getDeviceName()
                self._set_switch(device_name, "CONNECTION", "DISCONNECT")
                logger.info(f"Telescope {device_name} disconnected")

            if self._connected:
                self.client.disconnectServer()
                self._connected = False
                logger.info("Disconnected from INDI server")

            return True

        except Exception as e:
            logger.exception(f"Error disconnecting mount: {e}")
            return False


def run(mount_queue, console_queue, shared_state, log_queue,
        indi_host="localhost", indi_port=7624):
    """Run the INDI mount control process.

    Args:
        mount_queue: Queue for receiving mount commands
        console_queue: Queue for sending status messages
        shared_state: Shared state object
        log_queue: Queue for logging
        indi_host: INDI server hostname
        indi_port: INDI server port
    """
    MultiprocLogging.configurer(log_queue)
    mount_control = MountControlIndi(mount_queue, console_queue, shared_state,
                                      log_queue, indi_host, indi_port)
    try:
        mount_control.run()
    except KeyboardInterrupt:
        logger.info("Shutting down MountControlIndi.")
        raise
