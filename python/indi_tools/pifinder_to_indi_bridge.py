#!/usr/bin/env python3
"""
PiFinder to INDI Bridge Script

This script connects the PiFinder UI object selection to INDI telescope control.
It monitors the PiFinder's current selection and automatically sends target coordinates
to the telescope mount via INDI when a new object is selected.

Features:
- Connects to PiFinder API with authentication
- Monitors /api/current-selection for UIObjectDetails selections
- Converts J2000 coordinates to Epoch of Date (EOD)
- Sends TARGET_EOD_COORD to INDI telescope
- Change detection to avoid unnecessary updates
- Robust error handling and reconnection logic

Usage:
    python pifinder_to_indi_bridge.py [options]

    Options:
        --pifinder-host HOST    PiFinder host (default: localhost)
        --pifinder-port PORT    PiFinder port (default: 80)
        --indi-host HOST        INDI server host (default: localhost)
        --indi-port PORT        INDI server port (default: 7624)
        --telescope DEVICE      Telescope device name (default: auto-detect)
        --password PWD          PiFinder password (default: solveit)
        --interval SEC          Polling interval (default: 2.0)
        --verbose               Enable verbose logging
"""

import PyIndi
import requests
import time
import argparse
import threading
from astropy.time import Time
from astropy.coordinates import SkyCoord, ICRS, FK5, CIRS
from astropy import units as u
import logging


class PiFinderIndiClient(PyIndi.BaseClient):
    """INDI client for telescope control."""

    def __init__(self, telescope_name=None, verbose=False):
        super(PiFinderIndiClient, self).__init__()
        self.telescope_name = telescope_name
        self.verbose = verbose
        self.telescope_device = None
        self.equatorial_coord_property = None
        self.on_coord_set_property = None
        self.connection_property = None
        self.connected = False
        self.lock = threading.Lock()

        # Setup logging
        self.logger = logging.getLogger("IndiClient")
        if verbose:
            logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.INFO)

    def log(self, message, level=logging.INFO):
        """Log a message with timestamp."""
        if self.verbose or level >= logging.INFO:
            self.logger.log(level, message)

    def newDevice(self, device):
        """Called when a new INDI device is discovered."""
        device_name = device.getDeviceName()
        self.log(f"Discovered device: {device_name}")

        # Auto-detect telescope or match specified name
        if self.telescope_name is None:
            # Look for common telescope device patterns
            telescope_patterns = ["Telescope", "Mount", "EQMod", "Simulator"]
            if any(
                pattern.lower() in device_name.lower() for pattern in telescope_patterns
            ):
                with self.lock:
                    self.telescope_device = device
                    self.telescope_name = device_name
                self.log(f"Auto-detected telescope device: {device_name}")
        elif device_name == self.telescope_name:
            with self.lock:
                self.telescope_device = device
            self.log(f"Found specified telescope device: {device_name}")

    def newProperty(self, prop):
        """Called when a new property is discovered."""
        if not self.telescope_device:
            return

        device_name = prop.getDeviceName()
        prop_name = prop.getName()

        if device_name == self.telescope_name:
            # Look for the equatorial coordinate property
            if prop_name == "EQUATORIAL_EOD_COORD":
                with self.lock:
                    self.equatorial_coord_property = prop
                self.log(f"Found EQUATORIAL_EOD_COORD property for {device_name}")

            # Look for the coordinate set behavior property
            elif prop_name == "ON_COORD_SET":
                with self.lock:
                    self.on_coord_set_property = prop
                self.log(f"Found ON_COORD_SET property for {device_name}")

            # Look for connection property
            elif prop_name == "CONNECTION":
                with self.lock:
                    self.connection_property = prop
                self.log(f"Found CONNECTION property for {device_name}")
                self._check_connection_status()

    def updateProperty(self, prop):
        """Called when a property is updated."""
        if not self.telescope_device:
            return

        device_name = prop.getDeviceName()
        prop_name = prop.getName()

        if device_name == self.telescope_name and prop_name == "CONNECTION":
            self._check_connection_status()

    def _check_connection_status(self):
        """Check if telescope is connected."""
        if not self.connection_property:
            return

        switch_prop = PyIndi.PropertySwitch(self.connection_property)
        is_connected = False

        for widget in switch_prop:
            if widget.getName() == "CONNECT" and widget.getStateAsString() == "On":
                is_connected = True
                break

        with self.lock:
            self.connected = is_connected

        if is_connected:
            self.log(f"Telescope {self.telescope_name} is CONNECTED")
        else:
            self.log(f"Telescope {self.telescope_name} is DISCONNECTED")

    def serverConnected(self):
        """Called when connected to INDI server."""
        self.log("Connected to INDI server")

    def serverDisconnected(self, exit_code):
        """Called when disconnected from INDI server."""
        self.log(f"Disconnected from INDI server (exit code: {exit_code})")

    def is_ready(self):
        """Check if client is ready to send coordinates."""
        with self.lock:
            return (
                self.telescope_device is not None
                and self.equatorial_coord_property is not None
                and self.connected
            )

    def set_target_coordinates(self, ra_hours, dec_degrees):
        """Send target coordinates to telescope using proper INDI slew method."""
        if not self.is_ready():
            self.log("Telescope not ready for coordinate updates", logging.WARNING)
            return False

        try:
            with self.lock:
                # First, set ON_COORD_SET to TRACK so telescope tracks after slewing
                if self.on_coord_set_property:
                    coord_set_prop = PyIndi.PropertySwitch(self.on_coord_set_property)
                    # Reset all switches first
                    for widget in coord_set_prop:
                        widget.setState(PyIndi.ISS_OFF)
                    # Set TRACK switch to ON
                    for widget in coord_set_prop:
                        if widget.getName() == "TRACK":
                            widget.setState(PyIndi.ISS_ON)
                            break
                    self.sendNewProperty(coord_set_prop)
                    self.log("Set coordinate behavior to TRACK")

                # Now set the target coordinates using EQUATORIAL_EOD_COORD
                coord_prop = PyIndi.PropertyNumber(self.equatorial_coord_property)

                # Set RA and DEC values
                for widget in coord_prop:
                    if widget.getName() == "RA":
                        widget.setValue(ra_hours)
                        self.log(f"Setting RA to {ra_hours:.6f} hours")
                    elif widget.getName() == "DEC":
                        widget.setValue(dec_degrees)
                        self.log(f"Setting DEC to {dec_degrees:.6f} degrees")

                # Send the new coordinates - this triggers the slew
                self.sendNewProperty(coord_prop)
                self.log(
                    f"Sent slew command: RA={ra_hours:.6f}h, DEC={dec_degrees:.6f}°"
                )
                return True

        except Exception as e:
            self.log(f"Error setting coordinates: {e}", logging.ERROR)
            return False


class PiFinderApiBridge:
    """Bridge between PiFinder API and INDI telescope control."""

    def __init__(
        self,
        pifinder_host="localhost",
        pifinder_port=8080,
        password="solveit",
        indi_host="localhost",
        indi_port=7624,
        telescope_name=None,
        poll_interval=2.0,
        verbose=False,
    ):
        self.pifinder_host = pifinder_host
        self.pifinder_port = pifinder_port
        self.password = password
        self.indi_host = indi_host
        self.indi_port = indi_port
        self.poll_interval = poll_interval
        self.verbose = verbose

        # Session management
        self.session = requests.Session()
        self.logged_in = False

        # Target tracking
        self.last_target = None
        self.last_target_hash = None

        # INDI client
        self.indi_client = PiFinderIndiClient(telescope_name, verbose)

        # Setup logging
        self.logger = logging.getLogger("PiFinderBridge")
        if verbose:
            logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.INFO)

    def log(self, message, level=logging.INFO):
        """Log a message with timestamp."""
        if self.verbose or level >= logging.INFO:
            self.logger.log(level, message)

    def connect_indi(self):
        """Connect to INDI server."""
        self.log(f"Connecting to INDI server at {self.indi_host}:{self.indi_port}")
        self.indi_client.setServer(self.indi_host, self.indi_port)

        if not self.indi_client.connectServer():
            self.log(
                f"Failed to connect to INDI server at {self.indi_host}:{self.indi_port}",
                logging.ERROR,
            )
            return False

        # Wait for device discovery
        time.sleep(3)
        return True

    def login_pifinder(self):
        """Login to PiFinder API."""
        try:
            login_url = f"http://{self.pifinder_host}:{self.pifinder_port}/login"
            login_data = {"password": self.password}

            self.log(f"Logging into PiFinder at {login_url}")
            # Send as form data, not JSON
            response = self.session.post(login_url, data=login_data, timeout=10)

            if response.status_code == 200:
                self.logged_in = True
                self.log("Successfully logged into PiFinder")
                # The session cookies are automatically stored by requests.Session()
                return True
            else:
                self.log(
                    f"Login failed: {response.status_code} {response.text}",
                    logging.ERROR,
                )
                return False

        except Exception as e:
            self.log(f"Login error: {e}", logging.ERROR)
            return False

    def get_current_selection(self):
        """Get current selection from PiFinder API."""
        try:
            if not self.logged_in:
                if not self.login_pifinder():
                    return None

            api_url = f"http://{self.pifinder_host}:{self.pifinder_port}/api/current-selection"
            response = self.session.get(api_url, timeout=10)

            if response.status_code == 401:
                # Session expired, re-login
                self.logged_in = False
                if not self.login_pifinder():
                    return None
                response = self.session.get(api_url, timeout=10)

            if response.status_code == 200:
                return response.json()
            else:
                self.log(
                    f"API request failed: {response.status_code} {response.text}",
                    logging.ERROR,
                )
                return None

        except Exception as e:
            self.log(f"API request error: {e}", logging.ERROR)
            return None

    def j2000_to_eod(self, ra_j2000_hours, dec_j2000_degrees):
        """Convert J2000 coordinates to Epoch of Date (EOD) - apparent coordinates for current time."""
        try:
            # Create coordinate object in J2000 (ICRS)
            coord_j2000 = SkyCoord(
                ra=ra_j2000_hours * u.hour, dec=dec_j2000_degrees * u.deg, frame=ICRS
            )

            current_time = Time.now()

            # Try CIRS first (modern apparent coordinates)
            try:
                # CIRS (Celestial Intermediate Reference System) represents apparent coordinates
                # accounting for precession, nutation, and frame bias at the observation time
                coord_eod = coord_j2000.transform_to(CIRS(obstime=current_time))
                conversion_type = "CIRS"
            except Exception as cirs_error:
                self.log(
                    f"CIRS conversion failed, trying FK5: {cirs_error}", logging.WARNING
                )
                # Fallback to FK5 with current equinox (classical approach)
                coord_eod = coord_j2000.transform_to(FK5(equinox=current_time))
                conversion_type = "FK5"

            # Return as hours and degrees
            ra_eod_hours = coord_eod.ra.hour
            dec_eod_degrees = coord_eod.dec.degree

            self.log(
                f"Coordinate conversion ({conversion_type}): J2000({ra_j2000_hours:.6f}h, {dec_j2000_degrees:.6f}°) "
                f"-> EOD({ra_eod_hours:.6f}h, {dec_eod_degrees:.6f}°) at {current_time.iso}"
            )

            return ra_eod_hours, dec_eod_degrees

        except Exception as e:
            self.log(f"Coordinate conversion error: {e}", logging.ERROR)
            return None, None

    def process_selection(self, selection_data):
        """Process current selection and send to telescope if changed."""
        if not selection_data:
            return

        ui_type = selection_data.get("ui_type")

        if ui_type != "UIObjectDetails":
            # Clear target if not an object selection
            if self.last_target is not None:
                self.log("Selection cleared - no longer UIObjectDetails")
                self.last_target = None
                self.last_target_hash = None
            return

        # Extract object data
        object_data = selection_data.get("object", {})
        if not object_data:
            self.log("No object data in UIObjectDetails", logging.WARNING)
            return

        # Get J2000 coordinates
        ra_j2000_degrees = object_data.get("ra")  # PiFinder returns RA in degrees
        dec_j2000_degrees = object_data.get("dec")  # DEC in degrees
        object_name = object_data.get("name", "Unknown")

        if ra_j2000_degrees is None or dec_j2000_degrees is None:
            self.log(f"Missing coordinates for object {object_name}", logging.WARNING)
            return

        # Convert RA from degrees to hours for display and processing
        ra_j2000_hours = ra_j2000_degrees / 15.0

        # Create hash for change detection
        target_hash = hash((ra_j2000_degrees, dec_j2000_degrees, object_name))

        if target_hash == self.last_target_hash:
            # No change in target
            return

        self.log(f"New target selected: {object_name}")
        self.log(
            f"  J2000 coordinates: RA={ra_j2000_hours:.6f}h ({ra_j2000_degrees:.6f}°), DEC={dec_j2000_degrees:.6f}°"
        )

        # Convert to EOD using hours for RA (as expected by j2000_to_eod)
        ra_eod, dec_eod = self.j2000_to_eod(ra_j2000_hours, dec_j2000_degrees)
        if ra_eod is None or dec_eod is None:
            self.log("Failed to convert coordinates to EOD", logging.ERROR)
            return

        # Send to telescope
        if self.indi_client.is_ready():
            success = self.indi_client.set_target_coordinates(ra_eod, dec_eod)
            if success:
                self.last_target = object_name
                self.last_target_hash = target_hash
                self.log(f"Successfully set telescope target to {object_name}")
            else:
                self.log("Failed to set telescope coordinates", logging.ERROR)
        else:
            self.log("INDI telescope not ready", logging.WARNING)

    def run(self):
        """Main monitoring loop."""
        self.log("Starting PiFinder to INDI bridge")

        # Connect to INDI
        if not self.connect_indi():
            return False

        # Login to PiFinder
        if not self.login_pifinder():
            return False

        self.log(f"Bridge active - polling every {self.poll_interval} seconds")
        self.log("Press Ctrl+C to stop")

        try:
            while True:
                # Get current selection
                selection = self.get_current_selection()

                # Process selection and update telescope if needed
                self.process_selection(selection)

                # Wait before next poll
                time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            self.log("Bridge stopped by user")
        except Exception as e:
            self.log(f"Unexpected error: {e}", logging.ERROR)
        finally:
            self.log("Disconnecting from INDI server")
            self.indi_client.disconnectServer()
            self.log("Bridge shutdown complete")


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="PiFinder to INDI Bridge - Connect PiFinder object selection to telescope control"
    )

    parser.add_argument(
        "--pifinder-host",
        default="localhost",
        help="PiFinder host (default: localhost)",
    )
    parser.add_argument(
        "--pifinder-port", type=int, default=8080, help="PiFinder port (default: 80)"
    )
    parser.add_argument(
        "--indi-host", default="localhost", help="INDI server host (default: localhost)"
    )
    parser.add_argument(
        "--indi-port", type=int, default=7624, help="INDI server port (default: 7624)"
    )
    parser.add_argument(
        "--telescope", help="Telescope device name (default: auto-detect)"
    )
    parser.add_argument(
        "--password", default="solveit", help="PiFinder password (default: solveit)"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Polling interval in seconds (default: 2.0)",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    # Create and run bridge
    bridge = PiFinderApiBridge(
        pifinder_host=args.pifinder_host,
        pifinder_port=args.pifinder_port,
        password=args.password,
        indi_host=args.indi_host,
        indi_port=args.indi_port,
        telescope_name=args.telescope,
        poll_interval=args.interval,
        verbose=args.verbose,
    )

    bridge.run()


if __name__ == "__main__":
    main()
