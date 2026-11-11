# (C) 2025 Jens Scheidtmann
#
# This file is part of PiFinder.
#
# PiFinder is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
"""Mount control over INDI.

PiFinder starts the driver of the selected mount model in the local
indiserver (indi_drivers), connects with the pure-Python IndiClient, and
drives the mount with the standard INDI telescope properties.
"""

import logging
import time
from multiprocessing import Queue
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from PiFinder import indi_drivers
from PiFinder.indi_client import TELESCOPE_INTERFACE, IndiClient, IndiProperty
from PiFinder.mountcontrol_interface import (
    MountControlBase,
    MountDirections,
    MountDirectionsAltAz,
    MountDirectionsEquatorial,
)
from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.state import SharedStateObj

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


logger = logging.getLogger("MountControl.Indi")

POSITION = "EQUATORIAL_EOD_COORD"
# Time for the driver to define its device after "start" in the FIFO.
DEVICE_TIMEOUT_S = 10.0
# Time for the driver to open the port and talk to the mount.
CONNECT_TIMEOUT_S = 20.0


class MountControlIndi(MountControlBase):
    """MountControlBase on INDI.

    Args:
        model_label: the mount model label from the INDI driver XML, as the
            config stores it (see indi_drivers.MountModel).
        port: the serial port of the mount, for drivers that have DEVICE_PORT.
        baud: the serial speed, for drivers that have DEVICE_BAUD_RATE.
    """

    def __init__(
        self,
        mount_queue: Queue,
        console_queue: Queue,
        shared_state: SharedStateObj,
        log_queue: Optional[Queue],
        model_label: str,
        port: str = "/dev/ttyUSB0",
        baud: int = 9600,
        indi_host: str = "localhost",
        indi_port: int = 7624,
        target_tolerance_deg: float = 0.01,
    ):
        super().__init__(mount_queue, console_queue, shared_state)
        self.model_label = model_label
        self.port = port
        self.baud = baud
        self.log_queue = log_queue

        self.client = IndiClient(indi_host, indi_port)
        self.client.add_listener(self._on_property)
        self.device: Optional[str] = None

        self.current_time: float = 0.0  # Timestamp of last position update
        self._current_position_update_threshold = 1.5  # seconds

        self._target_ra: Optional[float] = None
        self._target_dec: Optional[float] = None
        self._target_tolerance_deg = target_tolerance_deg
        # True from a goto until the position state leaves Busy.
        self._slewing = False

        self.available_slew_rates: List[str] = []

        # Location is synced at init and again when it changes.
        self.last_periodic_update: float = 0.0
        self.periodic_update_interval: float = 30.0  # seconds
        self._last_synced_location: Optional[Tuple[float, float, float]] = None

    #
    # INDI events (reader thread of the client)
    #

    def _on_property(
        self,
        event: str,
        device: str,
        name: Optional[str],
        prop: Optional[IndiProperty],
    ) -> None:
        if event == "disconnected":
            logger.warning("Disconnected from indiserver")
            return
        if device != self.device or name != POSITION or prop is None:
            return
        if event not in ("def", "set"):
            return
        ra_hours = prop.elements.get("RA")
        dec_deg = prop.elements.get("DEC")
        if not isinstance(ra_hours, float) or not isinstance(dec_deg, float):
            return
        self._mount_current_position(ra_hours * 15.0, dec_deg, prop.state)

    def _mount_current_position(
        self, ra_deg: float, dec_deg: float, state: str = "Ok"
    ) -> None:
        self.current_ra = ra_deg
        self.current_dec = dec_deg
        self.current_time = time.time()
        self.mount_current_position(ra_deg, dec_deg)
        if not self._slewing or state == "Busy":
            return
        self._slewing = False
        if state == "Alert":
            logger.warning("Goto failed: the mount reports Alert")
            self.console_queue.put(["WARNING", _("Goto failed!")])
            self.mount_stopped()
            return
        logger.info(
            "Target reached: RA=%.4f°, Dec=%.4f° (target RA=%s, Dec=%s)",
            ra_deg,
            dec_deg,
            self._target_ra,
            self._target_dec,
        )
        # Make is_mount_moving() False at once.
        self.current_time -= self._current_position_update_threshold + 1.0
        self.mount_target_reached()

    #
    # Helpers
    #

    def _find_telescope(self, preferred: str) -> Optional[str]:
        """The device with the telescope interface, the preferred name first."""
        devices = self.client.devices()
        if preferred in devices:
            interface = self.client.device_interface(preferred)
            if interface is not None and interface & TELESCOPE_INTERFACE:
                return preferred
        for device in devices:
            interface = self.client.device_interface(device)
            if interface is not None and interface & TELESCOPE_INTERFACE:
                return device
        return None

    def _has(self, name: str) -> bool:
        return self.device is not None and (
            self.client.get_property(self.device, name) is not None
        )

    def _switch_on(self, name: str, element: str) -> bool:
        return self.client.get_value(self.device or "", name, element) is True

    def _set_switch(self, name: str, element: str) -> bool:
        return self.device is not None and self.client.set_switch(
            self.device, name, element
        )

    def _set_number(self, name: str, values: dict[str, float]) -> bool:
        return self.device is not None and self.client.set_number(
            self.device, name, values
        )

    def _configure_port(self) -> None:
        """Set the serial port and speed before CONNECT, if the driver has
        them. Drivers that use TCP or USB without a port skip this."""
        assert self.device is not None
        if (
            self._has("CONNECTION_MODE")
            and self.client.get_value(
                self.device, "CONNECTION_MODE", "CONNECTION_SERIAL"
            )
            is not None
        ):
            self._set_switch("CONNECTION_MODE", "CONNECTION_SERIAL")
        if self._has("DEVICE_PORT"):
            self.client.set_text(self.device, "DEVICE_PORT", {"PORT": self.port})
        baud = str(self.baud)
        if self.client.get_value(self.device, "DEVICE_BAUD_RATE", baud) is not None:
            self._set_switch("DEVICE_BAUD_RATE", baud)

    #
    # MountControlBase
    #

    def init_mount(
        self,
        solve_ra_deg: Optional[float] = None,
        solve_dec_deg: Optional[float] = None,
    ) -> bool:
        """Start the driver, connect the mount, sync location and time,
        unpark, track, and sync to the solve if one is given."""
        model = indi_drivers.find_model(self.model_label)
        if model is None:
            logger.error("Unknown mount model %r", self.model_label)
            self.console_queue.put(["WARNING", _("Select a mount")])
            return False
        if not indi_drivers.start_driver(model):
            self.console_queue.put(["WARNING", _("No INDI server")])
            return False
        if not self.client.is_connected() and not self.client.connect():
            logger.error(
                "Cannot connect to indiserver at %s:%s",
                self.client.host,
                self.client.port,
            )
            return False

        found: list[str] = []

        def telescope_found() -> bool:
            device = self._find_telescope(model.device_name)
            if device is not None:
                found.append(device)
            return device is not None

        self.client.wait_for(telescope_found, DEVICE_TIMEOUT_S)
        if not found:
            logger.error("No telescope device from driver %s", model.driver)
            return False
        self.device = found[0]
        logger.info("Telescope device: %s", self.device)

        if not self._switch_on("CONNECTION", "CONNECT"):
            self._configure_port()
            if not self._set_switch("CONNECTION", "CONNECT"):
                return False
            connected = self.client.wait_state(
                self.device, "CONNECTION", ("Ok", "Alert"), CONNECT_TIMEOUT_S
            )
            prop = self.client.get_property(self.device, "CONNECTION")
            if not connected or prop is None or prop.state != "Ok":
                logger.error("Mount did not connect on %s", self.port)
                self.console_queue.put(["WARNING", _("Mount not found")])
                return False
        if self.client.wait_property(self.device, POSITION, 5.0) is None:
            logger.error("Mount has no %s", POSITION)
            return False
        logger.info("Telescope %s connected", self.device)

        self.sync_mount_location_and_time(sync_time=True)

        slew_rates = self.client.get_property(self.device, "TELESCOPE_SLEW_RATE")
        self.available_slew_rates = list(slew_rates.elements) if slew_rates else []

        # The plate solve is the pointing model. The INDI alignment
        # subsystem would correct the synced position a second time.
        if self._switch_on("ALIGNMENT_SUBSYSTEM_ACTIVE", "ALIGNMENT SUBSYSTEM ACTIVE"):
            self.client.set_switch_off(self.device, "ALIGNMENT_SUBSYSTEM_ACTIVE")
            logger.info("INDI alignment subsystem turned off")

        if self._switch_on("TELESCOPE_PARK", "PARK"):
            logger.info("Mount is parked, unparking")
            if not self._set_switch("TELESCOPE_PARK", "UNPARK"):
                logger.warning("Failed to unpark mount, continuing anyway")
        if self._has("TELESCOPE_TRACK_MODE"):
            self._set_switch("TELESCOPE_TRACK_MODE", "TRACK_SIDEREAL")
        if self._has("TELESCOPE_TRACK_STATE"):
            self._set_switch("TELESCOPE_TRACK_STATE", "TRACK_ON")

        if solve_ra_deg is not None and solve_dec_deg is not None:
            if not self.sync_mount(solve_ra_deg, solve_dec_deg):
                logger.warning("Failed to sync mount to the solve during init")
        return True

    def sync_mount(
        self, current_position_ra_deg: float, current_position_dec_deg: float
    ) -> bool:
        """Sync the mount to the position (JNow degrees), then keep tracking."""
        if self.device is None:
            logger.error("Telescope device not available for sync")
            return False
        if not self._set_switch("ON_COORD_SET", "SYNC"):
            return False
        ok = self._set_number(
            POSITION,
            {"RA": current_position_ra_deg / 15.0, "DEC": current_position_dec_deg},
        )
        # Back to goto-and-track for the next coordinate send.
        self._set_switch("ON_COORD_SET", "TRACK")
        if not ok:
            return False
        if self._has("TELESCOPE_TRACK_STATE"):
            self._set_switch("TELESCOPE_TRACK_STATE", "TRACK_ON")
        logger.info(
            "Mount synced to RA=%.4f°, Dec=%.4f°",
            current_position_ra_deg,
            current_position_dec_deg,
        )
        self.current_ra = current_position_ra_deg
        self.current_dec = current_position_dec_deg
        return True

    def stop_mount(self) -> bool:
        if not self._set_switch("TELESCOPE_ABORT_MOTION", "ABORT"):
            logger.error("Failed to send abort motion")
            return False
        self._slewing = False
        logger.info("Mount stop command sent")
        self.mount_stopped()
        return True

    def _goto(self, ra_deg: float, dec_deg: float) -> bool:
        if not self._set_switch("ON_COORD_SET", "TRACK"):
            return False
        if not self._set_number(POSITION, {"RA": ra_deg / 15.0, "DEC": dec_deg}):
            return False
        self._slewing = True
        self.current_time = time.time()
        return True

    def move_mount_to_target(self, target_ra_deg: float, target_dec_deg: float) -> bool:
        """Goto the target (JNow degrees) and track."""
        if not self._goto(target_ra_deg, target_dec_deg):
            logger.error("Failed to send goto")
            return False
        logger.info("Goto RA=%.4f°, Dec=%.4f°", target_ra_deg, target_dec_deg)
        self._target_ra = target_ra_deg
        self._target_dec = target_dec_deg
        return True

    def is_mount_moving(self) -> bool:
        if self.device is not None:
            prop = self.client.get_property(self.device, POSITION)
            if prop is not None and prop.state == "Busy":
                return True
        return time.time() - self.current_time < self._current_position_update_threshold

    def adjust_mount_drift_rates(
        self, drift_rate_adjustment_ra: float, drift_rate_adjustment_dec: float
    ) -> bool:
        """Add the adjustments (degrees/second) to TELESCOPE_TRACK_RATE."""
        if self.device is None:
            return False
        rates = self.client.get_property(self.device, "TELESCOPE_TRACK_RATE")
        if rates is None:
            logger.warning("Mount has no TELESCOPE_TRACK_RATE, no drift control")
            return False
        ra_rate = rates.elements.get("TRACK_RATE_RA")
        dec_rate = rates.elements.get("TRACK_RATE_DE")
        if not isinstance(ra_rate, float) or not isinstance(dec_rate, float):
            return False
        # TELESCOPE_TRACK_RATE is in arcseconds per second.
        return self._set_number(
            "TELESCOPE_TRACK_RATE",
            {
                "TRACK_RATE_RA": ra_rate + drift_rate_adjustment_ra * 3600.0,
                "TRACK_RATE_DE": dec_rate + drift_rate_adjustment_dec * 3600.0,
            },
        )

    def move_mount_manual(
        self, direction: MountDirections, step_size_deg: float
    ) -> bool:
        """Move by one step with a goto to the current position plus the step."""
        if self.current_ra is None or self.current_dec is None:
            logger.error("Current mount position unknown, cannot move manually")
            self.console_queue.put(["WARNING", _("No position")])
            return False
        ra = self.current_ra
        dec = self.current_dec
        if direction in (MountDirectionsEquatorial.NORTH, MountDirectionsAltAz.UP):
            dec += step_size_deg
        elif direction in (MountDirectionsEquatorial.SOUTH, MountDirectionsAltAz.DOWN):
            dec -= step_size_deg
        elif direction in (MountDirectionsEquatorial.EAST, MountDirectionsAltAz.RIGHT):
            ra += step_size_deg
        elif direction in (MountDirectionsEquatorial.WEST, MountDirectionsAltAz.LEFT):
            ra -= step_size_deg
        else:
            logger.error("Unknown direction: %s", direction)
            return False
        ra %= 360.0
        dec = max(-90.0, min(90.0, dec))
        logger.info("Manual move %s by %.5f°", direction, step_size_deg)
        return self._goto(ra, dec)

    def disconnect_mount(self) -> bool:
        if self.device is not None and self.client.is_connected():
            self._set_switch("CONNECTION", "DISCONNECT")
            logger.info("Telescope %s disconnected", self.device)
        self.client.disconnect()
        return True

    def sync_mount_location_and_time(self, sync_time: bool = False) -> bool:
        """Send the location when it changes, and the UTC time if asked."""
        if self.device is None:
            return False
        location = self.shared_state.location()
        # Without a lock the location is the 0,0 default.
        if location is not None and location.lock:
            # INDI longitude is 0..360 degrees East. Rounded to about 10 m,
            # so GPS jitter does not resend it.
            current = (
                round(location.lat, 4),
                round(location.lon % 360.0, 4),
                round(location.altitude or 0.0),
            )
            if current != self._last_synced_location and self._set_number(
                "GEOGRAPHIC_COORD",
                {"LAT": current[0], "LONG": current[1], "ELEV": current[2]},
            ):
                self._last_synced_location = current
                logger.info("Mount location: %s", current)
        dt = self.shared_state.datetime()
        if sync_time and dt is not None and self._has("TIME_UTC"):
            self.client.set_text(
                self.device,
                "TIME_UTC",
                {"UTC": dt.strftime("%Y-%m-%dT%H:%M:%S"), "OFFSET": "0"},
            )
            logger.info("Mount time: %s UTC", dt)
        return True

    def periodic_mount_task(self) -> None:
        if self.last_periodic_update + self.periodic_update_interval < time.time():
            self.last_periodic_update = time.time()
            self.sync_mount_location_and_time()


def run(
    mount_queue: Queue,
    console_queue: Queue,
    shared_state: SharedStateObj,
    log_queue: Optional[Queue],
    model_label: str,
    port: str = "/dev/ttyUSB0",
    baud: int = 9600,
):
    """Process target for mount control."""
    if log_queue is not None:
        MultiprocLogging.configurer(log_queue)
    mount_control = MountControlIndi(
        mount_queue, console_queue, shared_state, log_queue, model_label, port, baud
    )
    try:
        mount_control.run()
    except KeyboardInterrupt:
        logger.info("Shutting down MountControlIndi.")
        raise
