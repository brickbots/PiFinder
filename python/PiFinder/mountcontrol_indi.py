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
import math
import time
from multiprocessing import Queue
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Tuple

from PiFinder import config, indi_drivers
from PiFinder import track_rates
from PiFinder.indi_client import TELESCOPE_INTERFACE, IndiClient, IndiProperty
from PiFinder.mount_settings import MountSettings
from PiFinder.mountcontrol_interface import (
    MountControlBase,
    angular_distance,
    MountControlPhases,
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
# After a goto, a position update with state Ok ends the slew only after the
# driver reported Busy, or after this time: the driver's reply to an earlier
# sync can come after the goto was sent.
SLEW_START_GRACE_S = 3.0
# A slew that ends further than this from its own target was interrupted
# (a hand controller, a limit, or a driver that stops on a new location).
GOTO_END_TOLERANCE_DEG = 1.0
# A slew with no end report counts as ended after this time.
SLEW_TIMEOUT_S = 300.0
# A direction part above this (about 22.5° off the axis) moves that axis.
MOTION_AXIS_THRESHOLD = 0.38
# Time for the driver to define CONNECTION_MODE after DRIVER_INFO.
CONNECTION_MODE_WAIT_S = 3.0
# The sidereal rate of TELESCOPE_TRACK_RATE, in arcseconds per second. With
# TRACK_RATE_RA at this value the RA of the mount does not change.
SIDEREAL_RATE_ARCSEC_S = 15.041067
# The sign check of the custom track rates needs this much motion.
RATE_CHECK_MIN_S = 0.9
RATE_CHECK_MIN_DEG_S = 0.002


def _moved_against(moved_deg_s: float, requested_deg_s: float) -> bool:
    """The axis moved clearly in the direction opposite to the request."""
    return (
        abs(requested_deg_s) >= RATE_CHECK_MIN_DEG_S
        and abs(moved_deg_s) >= abs(requested_deg_s) / 2.0
        and (moved_deg_s > 0) != (requested_deg_s > 0)
    )


# Switches that are on when the driver reports an alt-az mount: the
# standard INDI mount type, and the mount type of the OnStep driver.
ALTAZ_SWITCHES = (
    ("TELESCOPE_MOUNT_TYPE", "ALTAZ"),
    ("MOUNT_TYPE", "MOUNT_TYPE_ALTAZ"),
)
# A drift grew when it is larger than the last one by this many standard
# errors of the difference. A wrong axis direction makes the drift grow by
# the correction gain (0.7), and each drift is at least 4 standard errors
# (DRIFT_SIGNIFICANCE_SE), so this limit must stay below about 1.4.
DRIFT_GREW_SE = 1.0


def _drift_grew(last: float, last_se: float, new: float, new_se: float) -> bool:
    """The drift after a correction has the same direction and is larger:
    the correction went the wrong way.

    A value of 0.0 is an axis with no significant drift, and it never
    shows a growth. The growth must be larger than the noise of the two
    values (their standard errors)."""
    if last == 0.0 or new == 0.0 or (last > 0) != (new > 0):
        return False
    return abs(new) - abs(last) > DRIFT_GREW_SE * math.hypot(last_se, new_se)


class MountControlIndi(MountControlBase):
    """MountControlBase on INDI.

    The settings (mount_settings.MountSettings) give the mount model label
    from the INDI driver XML, and the connection: "usb" with a serial port
    and speed, or "wifi" with "host:port". An empty host or port keeps the
    driver's own value (the AZ-GTi driver defaults to 192.168.4.1 port
    11880, for example). A reload_config command reads them again with
    load_settings.
    """

    def __init__(
        self,
        mount_queue: Queue,
        console_queue: Queue,
        shared_state: SharedStateObj,
        log_queue: Optional[Queue],
        settings: MountSettings,
        load_settings: Optional[Callable[[], MountSettings]] = None,
        indi_host: str = "localhost",
        indi_port: int = 7624,
        target_tolerance_deg: float = 0.01,
    ):
        super().__init__(mount_queue, console_queue, shared_state)
        self.settings = settings
        self._load_settings = load_settings or settings_from_config
        self.log_queue = log_queue
        self.indi_host = indi_host
        self.indi_port = indi_port
        if not settings.enabled:
            self.state = MountControlPhases.MOUNT_UNKNOWN

        self.client = self._new_client()
        self.device: Optional[str] = None

        self.current_time: float = 0.0  # Timestamp of last position update
        self._current_position_update_threshold = 1.5  # seconds

        self._target_ra: Optional[float] = None
        self._target_dec: Optional[float] = None
        self._target_tolerance_deg = target_tolerance_deg
        # True from a goto until the slew ends (see SLEW_START_GRACE_S).
        self._slewing = False
        self._slew_busy_seen = False
        self._slew_start = 0.0
        self._slew_target: Optional[Tuple[float, float]] = None
        # The track mode is Custom after a drift compensation.
        self._custom_tracking = False
        # The signs of the custom track rates of this driver (set_track_rates).
        self._ra_rate_sign = -1.0
        self._dec_rate_sign = 1.0
        self._rate_sample: Optional[tuple] = None
        self._ra_against = 0
        self._dec_against = 0
        # The lunar or solar rate as custom rates, for a driver without
        # TRACK_LUNAR or TRACK_SOLAR (see refresh_track_rate), or None.
        self._body_custom_rate: Optional[str] = None
        self._body_rate_time = 0.0
        # The last drift adjustment and its standard error per axis
        # (ra, ra_se, dec, dec_se), to check the axis directions.
        self._last_drift: Optional[Tuple[float, float, float, float]] = None

        self.available_slew_rates: List[str] = []

        # Location is synced at init and again when it changes.
        self.last_periodic_update: float = 0.0
        self.periodic_update_interval: float = 30.0  # seconds
        self._last_synced_location: Optional[Tuple[float, float, float]] = None

    @property
    def model_label(self) -> str:
        return self.settings.model

    @property
    def port(self) -> str:
        return self.settings.port

    @property
    def baud(self) -> int:
        return self.settings.baud

    @property
    def connection(self) -> str:
        return self.settings.connection

    @property
    def address(self) -> str:
        return self.settings.address

    def status_text(self) -> str:
        if not self.settings.enabled:
            return _("Off")
        return super().status_text()

    def status_model(self) -> str:
        return self.settings.model

    def _new_client(self) -> IndiClient:
        client = IndiClient(self.indi_host, self.indi_port)
        client.add_listener(self._on_property)
        return client

    def reload_settings(self) -> None:
        """Apply changed settings at once: disconnect, change the driver if
        the model changed, and connect again if mount control is on."""
        new = self._load_settings()
        if new == self.settings:
            return
        old = self.settings
        logger.info("Mount settings changed: %s", new)
        if self.device is not None or self.client.is_connected():
            self.disconnect_mount()
        self.device = None
        self._slewing = False
        self._custom_tracking = False
        self._last_drift = None
        self._last_error = ""
        if not new.enabled or new.model != old.model:
            indi_drivers.stop_driver()
            self._ra_rate_sign = -1.0
            self._dec_rate_sign = 1.0
        self.settings = new
        self.client = self._new_client()
        self._last_synced_location = None
        if new.enabled:
            self.state = MountControlPhases.MOUNT_INIT_TELESCOPE
            self.notify(_("Mount settings applied"))
        else:
            self.state = MountControlPhases.MOUNT_UNKNOWN
            self.notify(_("Mount control off"))

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
        if not self._slewing:
            return
        if state == "Busy":
            self._slew_busy_seen = True
            return
        if (
            not self._slew_busy_seen
            and time.time() - self._slew_start < SLEW_START_GRACE_S
        ):
            # Not this goto's end yet, for example the reply to a sync.
            return
        self._slewing = False
        if self._slew_target is not None and state != "Alert":
            off = angular_distance(ra_deg, dec_deg, *self._slew_target)
            if off > GOTO_END_TOLERANCE_DEG:
                logger.warning("Slew ended %.2f° from its target: interrupted", off)
                self.warn(_("Goto interrupted"))
                self.mount_stopped()
                return
        if state == "Alert":
            logger.warning("Goto failed: the mount reports Alert")
            self.warn(_("Goto failed!"))
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

    def _configure_connection(self) -> bool:
        """Set the connection of the driver before CONNECT: the serial port
        and speed for USB, or the network address for WiFi. A driver
        without these properties keeps its own settings."""
        assert self.device is not None
        # The driver defines its connection properties a moment after
        # DRIVER_INFO. Drivers without a connection plugin have none.
        self.client.wait_property(
            self.device, "CONNECTION_MODE", CONNECTION_MODE_WAIT_S
        )
        if self.connection == "wifi":
            return self._configure_network()
        if (
            self.client.get_value(self.device, "CONNECTION_MODE", "CONNECTION_SERIAL")
            is not None
        ):
            self._set_switch("CONNECTION_MODE", "CONNECTION_SERIAL")
        if self._has("DEVICE_PORT"):
            self.client.set_text(self.device, "DEVICE_PORT", {"PORT": self.port})
        baud = str(self.baud)
        if self.client.get_value(self.device, "DEVICE_BAUD_RATE", baud) is not None:
            self._set_switch("DEVICE_BAUD_RATE", baud)
        return True

    def _configure_network(self) -> bool:
        assert self.device is not None
        if (
            self.client.get_value(self.device, "CONNECTION_MODE", "CONNECTION_TCP")
            is None
        ):
            logger.error("Driver of %s has no network connection", self.device)
            self.warn(_("No WiFi in driver"))
            return False
        self._set_switch("CONNECTION_MODE", "CONNECTION_TCP")
        host, port = split_address(self.address)
        values = {}
        if host:
            values["ADDRESS"] = host
        if port:
            values["PORT"] = port
        if values:
            # The TCP connection defines DEVICE_ADDRESS when it is the mode.
            if self.client.wait_property(self.device, "DEVICE_ADDRESS", 5.0) is None:
                logger.error("Driver of %s has no DEVICE_ADDRESS", self.device)
                return False
            self.client.set_text(self.device, "DEVICE_ADDRESS", values)
        return True

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
        if not self.settings.enabled:
            return False
        model = indi_drivers.find_model(self.model_label)
        if model is None:
            logger.error("Unknown mount model %r", self.model_label)
            self.warn(_("Select a mount"))
            return False
        if not indi_drivers.start_driver(model):
            self.warn(_("No INDI server"))
            return False
        if not self.client.is_connected() and not self.client.connect():
            logger.error(
                "Cannot connect to indiserver at %s:%s",
                self.client.host,
                self.client.port,
            )
            self._last_error = _("No INDI server")
            return False

        found: list[str] = []

        def telescope_found() -> bool:
            device = self._find_telescope(model.device_name)
            if device is not None:
                found.append(device)
            return device is not None

        self.client.wait_for(telescope_found, DEVICE_TIMEOUT_S)
        if not found:
            # The running-driver record can be stale, for example when
            # indiserver gave up on a crashing driver. Start it again.
            logger.warning("No telescope device, starting %s again", model.driver)
            indi_drivers.stop_driver()
            if indi_drivers.start_driver(model):
                self.client.wait_for(telescope_found, DEVICE_TIMEOUT_S)
        if not found:
            logger.error("No telescope device from driver %s", model.driver)
            self._last_error = _("Driver failed")
            return False
        self.device = found[0]
        logger.info("Telescope device: %s", self.device)

        if not self._switch_on("CONNECTION", "CONNECT"):
            if not self._configure_connection():
                return False
            if not self._set_switch("CONNECTION", "CONNECT"):
                return False
            connected = self.client.wait_state(
                self.device, "CONNECTION", ("Ok", "Alert"), CONNECT_TIMEOUT_S
            )
            prop = self.client.get_property(self.device, "CONNECTION")
            if not connected or prop is None or prop.state != "Ok":
                logger.error("Mount did not connect on %s", self.where())
                self.warn(_("Mount not found"))
                return False
        if self.client.wait_property(self.device, POSITION, 5.0) is None:
            logger.error("Mount has no %s", POSITION)
            self._last_error = _("Mount not ready")
            return False
        logger.info("Telescope %s connected", self.device)

        self.sync_mount_location_and_time(sync_time=True)

        slew_rates = self.client.get_property(self.device, "TELESCOPE_SLEW_RATE")
        self.available_slew_rates = list(slew_rates.elements) if slew_rates else []

        # The INDI alignment subsystem stays as the driver has it: drivers
        # such as the AZ-GTi driver and the newer telescope simulator do a
        # sync through it.

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
        self._slew_busy_seen = False
        self._slew_start = time.time()
        self._slew_target = (ra_deg % 360.0, dec_deg)
        self.current_time = time.time()
        return True

    def move_mount_to_target(self, target_ra_deg: float, target_dec_deg: float) -> bool:
        """Goto the target (JNow degrees) and track."""
        if self._custom_tracking:
            # Drift rates belong to the old target.
            self._set_switch("TELESCOPE_TRACK_MODE", "TRACK_SIDEREAL")
            self._custom_tracking = False
        self._last_drift = None
        if not self._goto(target_ra_deg, target_dec_deg):
            logger.error("Failed to send goto")
            return False
        logger.info("Goto RA=%.4f°, Dec=%.4f°", target_ra_deg, target_dec_deg)
        self._target_ra = target_ra_deg
        self._target_dec = target_dec_deg
        return True

    def is_mount_moving(self) -> bool:
        if self._slewing and time.time() - self._slew_start < SLEW_TIMEOUT_S:
            return True
        if self.device is not None:
            prop = self.client.get_property(self.device, POSITION)
            if prop is not None and prop.state == "Busy":
                return True
        return time.time() - self.current_time < self._current_position_update_threshold

    def is_slewing(self) -> bool:
        return self._slewing and time.time() - self._slew_start < SLEW_TIMEOUT_S

    def is_altaz(self) -> bool:
        """True when the driver reports an alt-az mount. A driver without
        a mount type property gives False: the type is then unknown."""
        if self.device is None:
            return False
        return any(self._switch_on(name, element) for name, element in ALTAZ_SWITCHES)

    def adjust_mount_drift_rates(
        self,
        drift_rate_adjustment_ra: float,
        drift_rate_adjustment_dec: float,
        ra_se: float = 0.0,
        dec_se: float = 0.0,
    ) -> bool:
        """Cancel a drift of the pointing (degrees/second) with custom rates.

        INDI applies TELESCOPE_TRACK_RATE only in the TRACK_CUSTOM track
        mode. A mount without that mode keeps sidereal tracking, and drift
        compensation does nothing.

        The direction of the rate axes differs between drivers. With
        TRACK_RATE_RA above sidereal the RA axis turns faster and the RA of
        the pointing decreases. In the INDI telescope simulator a positive
        TRACK_RATE_DE makes the Dec decrease, and other drivers can do the
        opposite. If a drift has the same direction as the last one and is
        larger by more than the noise (see _drift_grew), the last correction
        went the wrong way: the axis turns its direction before this
        correction.

        An axis rate that changes its sign goes through zero (see below).
        """
        if self.device is None:
            return False
        if (
            self.client.get_value(self.device, "TELESCOPE_TRACK_MODE", "TRACK_CUSTOM")
            is None
        ):
            logger.info("Mount has no custom tracking, no drift compensation")
            return True
        rates = self.client.get_property(self.device, "TELESCOPE_TRACK_RATE")
        if rates is None:
            logger.warning("Mount has no TELESCOPE_TRACK_RATE, no drift control")
            return False
        ra_rate = rates.elements.get("TRACK_RATE_RA")
        dec_rate = rates.elements.get("TRACK_RATE_DE")
        if not isinstance(ra_rate, float) or not isinstance(dec_rate, float):
            return False
        if not self._custom_tracking and self.track_rate != track_rates.SIDEREAL:
            # TRACK_LUNAR or TRACK_SOLAR: the drift is on top of that rate.
            body = self._body_rate_values(self.track_rate)
            if body is not None:
                ra_rate, dec_rate = body["TRACK_RATE_RA"], body["TRACK_RATE_DE"]
        # The measured drift replaces the minute updates of a body rate.
        self._body_custom_rate = None
        self._check_drift_directions(
            drift_rate_adjustment_ra, ra_se, drift_rate_adjustment_dec, dec_se
        )
        if not self._custom_tracking:
            if not self._set_switch("TELESCOPE_TRACK_MODE", "TRACK_CUSTOM"):
                return False
            self._custom_tracking = True
        # TELESCOPE_TRACK_RATE is in arcseconds per second. The pointing
        # must move against the drift.
        new_ra = ra_rate - self._ra_rate_sign * drift_rate_adjustment_ra * 3600.0
        new_dec = dec_rate - self._dec_rate_sign * drift_rate_adjustment_dec * 3600.0
        ok = self._set_track_rate_values(new_ra, new_dec)
        if ok:
            self._last_drift = (
                drift_rate_adjustment_ra,
                ra_se,
                drift_rate_adjustment_dec,
                dec_se,
            )
        return ok

    def _check_drift_directions(
        self, ra_drift: float, ra_se: float, dec_drift: float, dec_se: float
    ) -> None:
        """Turn the direction of an axis whose last correction made the
        drift larger."""
        if self._last_drift is None:
            return
        last_ra, last_ra_se, last_dec, last_dec_se = self._last_drift
        if _drift_grew(last_ra, last_ra_se, ra_drift, ra_se):
            self._ra_rate_sign = -self._ra_rate_sign
            logger.info(
                "RA track rate direction of this driver: %+.0f", self._ra_rate_sign
            )
        if _drift_grew(last_dec, last_dec_se, dec_drift, dec_se):
            self._dec_rate_sign = -self._dec_rate_sign
            logger.info(
                "Dec track rate direction of this driver: %+.0f", self._dec_rate_sign
            )

    def _set_track_rate_values(self, ra: float, dec: float) -> bool:
        """Set TELESCOPE_TRACK_RATE (arcseconds per second).

        While tracking, an INDI driver ignores a rate that has the opposite
        sign of its current rate ("Cannot reverse tracking"), and it sends
        no reply. A rate of zero is always accepted, so an axis whose sign
        changes goes through zero first.
        """
        if self.device is None:
            return False
        rates = self.client.get_property(self.device, "TELESCOPE_TRACK_RATE")
        current = rates.elements if rates is not None else {}
        now_ra = current.get("TRACK_RATE_RA")
        now_dec = current.get("TRACK_RATE_DE")
        reverse_ra = isinstance(now_ra, float) and now_ra * ra < 0
        reverse_dec = isinstance(now_dec, float) and now_dec * dec < 0
        if reverse_ra or reverse_dec:
            if not self._set_number(
                "TELESCOPE_TRACK_RATE",
                {
                    "TRACK_RATE_RA": 0.0 if reverse_ra else ra,
                    "TRACK_RATE_DE": 0.0 if reverse_dec else dec,
                },
            ):
                return False
        return self._set_number(
            "TELESCOPE_TRACK_RATE", {"TRACK_RATE_RA": ra, "TRACK_RATE_DE": dec}
        )

    def set_tracking(self, on: bool) -> bool:
        if self.device is None or not self._has("TELESCOPE_TRACK_STATE"):
            return False
        return self._set_switch(
            "TELESCOPE_TRACK_STATE", "TRACK_ON" if on else "TRACK_OFF"
        )

    def set_track_rates(self, ra_rate_deg_s: float, dec_rate_deg_s: float) -> bool:
        """Track a moving object: RA and Dec change at these rates (JNow).

        INDI applies TELESCOPE_TRACK_RATE only in the TRACK_CUSTOM mode. The
        sign of the rates differs between drivers: in the telescope
        simulator a TRACK_RATE_RA above sidereal makes the RA decrease, and a
        positive TRACK_RATE_DE makes the Dec decrease. Each call compares the
        motion since the last call with the rates of that call, and turns
        the sign of an axis that moved the wrong way. A mount without
        TRACK_CUSTOM, or one that refuses the rates, returns False.
        """
        if self.device is None:
            return False
        if (
            self.client.get_value(self.device, "TELESCOPE_TRACK_MODE", "TRACK_CUSTOM")
            is None
        ):
            return False
        if not self._custom_tracking:
            if not self._set_switch("TELESCOPE_TRACK_MODE", "TRACK_CUSTOM"):
                return False
            self._custom_tracking = True
            self._rate_sample = None
        self._check_rate_signs()
        values = {
            "TRACK_RATE_RA": SIDEREAL_RATE_ARCSEC_S
            + self._ra_rate_sign * ra_rate_deg_s * 3600.0,
            "TRACK_RATE_DE": self._dec_rate_sign * dec_rate_deg_s * 3600.0,
        }
        rates = self.client.get_property(self.device, "TELESCOPE_TRACK_RATE")
        current = rates.elements if rates is not None else {}
        reverse = False
        for name, value in values.items():
            now = current.get(name)
            if isinstance(now, float) and now * value < 0:
                reverse = True
        ok = self._set_track_rate_values(
            values["TRACK_RATE_RA"], values["TRACK_RATE_DE"]
        )
        if reverse or not ok:
            # The motion right after a reversal tells nothing about the sign.
            self._rate_sample = None
        elif self._rate_sample is None and self.current_ra is not None:
            self._rate_sample = (
                self.current_time,
                self.current_ra,
                self.current_dec,
                ra_rate_deg_s,
                dec_rate_deg_s,
            )
        return ok

    def _check_rate_signs(self) -> None:
        """Turn the sign of an axis that moved against the requested rate.

        The motion is measured between two position reports of the driver,
        over at least RATE_CHECK_MIN_S. An axis turns its sign after two
        such measurements in a row against the request.
        """
        sample = self._rate_sample
        if sample is None or self.current_ra is None or self.current_dec is None:
            return
        start, ra0, dec0, ra_rate, dec_rate = sample
        seconds = self.current_time - start
        if seconds < RATE_CHECK_MIN_S:
            return
        self._rate_sample = None
        ra_moved = ((self.current_ra - ra0 + 540.0) % 360.0 - 180.0) / seconds
        dec_moved = (self.current_dec - dec0) / seconds
        self._ra_against = (
            self._ra_against + 1 if _moved_against(ra_moved, ra_rate) else 0
        )
        self._dec_against = (
            self._dec_against + 1 if _moved_against(dec_moved, dec_rate) else 0
        )
        if self._ra_against >= 2:
            self._ra_rate_sign = -self._ra_rate_sign
            self._ra_against = 0
            logger.info("RA track rate sign of this driver: %+.0f", self._ra_rate_sign)
        if self._dec_against >= 2:
            self._dec_rate_sign = -self._dec_rate_sign
            self._dec_against = 0
            logger.info(
                "Dec track rate sign of this driver: %+.0f", self._dec_rate_sign
            )

    def apply_track_rate(self, rate: str) -> bool:
        """Sidereal, lunar or solar tracking: the INDI track mode if the
        driver has it, else custom rates from the ephemeris."""
        self._body_custom_rate = None
        if self.device is None:
            return rate == track_rates.SIDEREAL
        mode = track_rates.INDI_TRACK_MODES[rate]
        if rate == track_rates.SIDEREAL:
            if self._custom_tracking:
                self.restore_sidereal_tracking()
            elif self._has("TELESCOPE_TRACK_MODE"):
                self._set_switch("TELESCOPE_TRACK_MODE", mode)
            return True
        if self.client.get_value(self.device, "TELESCOPE_TRACK_MODE", mode) is not None:
            self.restore_sidereal_tracking()
            return self._set_switch("TELESCOPE_TRACK_MODE", mode)
        if (
            self.client.get_value(self.device, "TELESCOPE_TRACK_MODE", "TRACK_CUSTOM")
            is None
        ):
            return False
        values = self._body_rate_values(rate)
        if values is None:
            return False
        if not self._custom_tracking:
            if not self._set_switch("TELESCOPE_TRACK_MODE", "TRACK_CUSTOM"):
                return False
            self._custom_tracking = True
        if not self._set_track_rate_values(
            values["TRACK_RATE_RA"], values["TRACK_RATE_DE"]
        ):
            return False
        self._body_custom_rate = rate
        self._body_rate_time = time.time()
        logger.info("%s rate as custom track rates: %s", rate, values)
        return True

    def refresh_track_rate(self) -> None:
        """The rates of the Moon change in hours: update them every minute."""
        if self._body_custom_rate is None:
            return
        if time.time() - self._body_rate_time < track_rates.RATE_STEP_S:
            return
        values = self._body_rate_values(self._body_custom_rate)
        if values is not None and self._set_track_rate_values(
            values["TRACK_RATE_RA"], values["TRACK_RATE_DE"]
        ):
            self._body_rate_time = time.time()

    def _body_rate_values(self, rate: str) -> Optional[dict[str, float]]:
        """TELESCOPE_TRACK_RATE values for the Moon or the Sun, or None."""
        location = self.shared_state.location()
        dt = self.shared_state.datetime()
        if location is None or not location.lock or dt is None:
            return None
        rates = track_rates.body_rates(
            rate, location.lat, location.lon, location.altitude, dt
        )
        if rates is None:
            return None
        ra_rate, dec_rate = rates
        return {
            "TRACK_RATE_RA": SIDEREAL_RATE_ARCSEC_S
            + self._ra_rate_sign * ra_rate * 3600.0,
            "TRACK_RATE_DE": self._dec_rate_sign * dec_rate * 3600.0,
        }

    def restore_sidereal_tracking(self) -> None:
        self._body_custom_rate = None
        if self.device is None or not self._custom_tracking:
            return
        self._set_track_rate_values(SIDEREAL_RATE_ARCSEC_S, 0.0)
        self._set_switch("TELESCOPE_TRACK_MODE", "TRACK_SIDEREAL")
        self._custom_tracking = False

    def move_mount_manual(
        self, direction: MountDirections, step_size_deg: float
    ) -> bool:
        """Move by one step with a goto to the current position plus the step."""
        if self.current_ra is None or self.current_dec is None:
            logger.error("Current mount position unknown, cannot move manually")
            self.warn(_("No position"))
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

    def where(self) -> str:
        """The port or the network address, for messages."""
        if self.connection == "wifi":
            return self.address or "the driver address"
        return self.port

    def move_mount_offset(
        self, north: float, east: float, step_size_deg: float
    ) -> bool:
        """Move by one step in a sky direction, as a goto from the current
        position. East is +RA; an RA step grows with 1/cos(Dec)."""
        if self.current_ra is None or self.current_dec is None:
            logger.error("Current mount position unknown, cannot move manually")
            self.warn(_("No position"))
            return False
        dec = max(-90.0, min(90.0, self.current_dec + north * step_size_deg))
        cos_dec = max(math.cos(math.radians(self.current_dec)), 1e-3)
        ra = (self.current_ra + east * step_size_deg / cos_dec) % 360.0
        logger.info("Move N %+.2f E %+.2f by %.5f°", north, east, step_size_deg)
        return self._goto(ra, dec)

    def start_motion(self, north: float, east: float, fastest: bool = False) -> bool:
        """Move with TELESCOPE_MOTION_NS/WE until stop_motion. A diagonal
        moves both axes. The slew rate is the middle of the driver's rates,
        or the fastest rate."""
        if self.device is None:
            return False
        rates = self.client.get_property(self.device, "TELESCOPE_SLEW_RATE")
        if rates is not None and rates.elements:
            names = list(rates.elements)
            self._set_switch(
                "TELESCOPE_SLEW_RATE", names[-1] if fastest else names[len(names) // 2]
            )
        moved = False
        if abs(north) > MOTION_AXIS_THRESHOLD:
            element = "MOTION_NORTH" if north > 0 else "MOTION_SOUTH"
            moved = self._set_switch("TELESCOPE_MOTION_NS", element) or moved
        if abs(east) > MOTION_AXIS_THRESHOLD:
            element = "MOTION_EAST" if east > 0 else "MOTION_WEST"
            moved = self._set_switch("TELESCOPE_MOTION_WE", element) or moved
        logger.info("Continuous move N %+.2f E %+.2f: %s", north, east, moved)
        return moved

    def stop_motion(self) -> bool:
        if self.device is None:
            return False
        ok = True
        for name in ("TELESCOPE_MOTION_NS", "TELESCOPE_MOTION_WE"):
            if self._has(name):
                ok = self.client.set_switch_off(self.device, name) and ok
        logger.info("Continuous move stopped")
        return ok

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
        # Some drivers stop a slew when the location changes, so the
        # location waits until the mount stands still.
        if self.is_mount_moving():
            return
        if self.last_periodic_update + self.periodic_update_interval < time.time():
            self.last_periodic_update = time.time()
            self.sync_mount_location_and_time()


def split_address(address: str) -> Tuple[str, str]:
    """Split "host:port" into host and port. Either part can be empty."""
    host, sep, port = address.strip().rpartition(":")
    if not sep:
        return address.strip(), ""
    return host, port


def settings_from_config() -> MountSettings:
    return MountSettings.from_config(config.Config())


def run(
    mount_queue: Queue,
    console_queue: Queue,
    shared_state: SharedStateObj,
    log_queue: Optional[Queue],
):
    """Process target for mount control. It runs while PiFinder runs, idle
    while mount control is off."""
    if log_queue is not None:
        MultiprocLogging.configurer(log_queue)
    mount_control = MountControlIndi(
        mount_queue, console_queue, shared_state, log_queue, settings_from_config()
    )
    try:
        mount_control.run()
    except KeyboardInterrupt:
        logger.info("Shutting down MountControlIndi.")
        raise
