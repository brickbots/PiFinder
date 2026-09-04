import io
import json
import logging
import time
import uuid
import os
import argparse
import sys
import multiprocessing
from datetime import timezone

import pydeepskylog as pds
from PIL import Image
from PiFinder import utils, calc_utils, config
from PiFinder import data_browser
from PiFinder import timez
from PiFinder.db.observations_db import (
    ObservationsDatabase,
)
from PiFinder.equipment import (
    EYEPIECE_LIMITS,
    MOUNT_TYPES,
    NAME_MAX_LENGTH,
    TELESCOPE_LIMITS,
    Eyepiece,
    Telescope,
    format_measurement,
)
from PiFinder.keyboard_interface import KeyboardInterface
from PiFinder.multiproclogging import MultiprocLogging

from flask import Flask, request, jsonify, send_file, redirect, session, make_response
from urllib.parse import quote
from flask_babel import Babel, gettext  # type: ignore[import-untyped]
from werkzeug.routing import IntegerConverter
from waitress import serve as waitress_serve

from PiFinder import i18n  # noqa: F401

# Type annotation for the global _ function installed by gettext.install()
import builtins

_ = builtins._  # type: ignore[attr-defined]


# Custom converter to handle negative integers in Flask routes
class SignedIntConverter(IntegerConverter):
    regex = r"-?\d+"


sys_utils = utils.get_sys_utils()

logger = logging.getLogger("Server")
logs_logger = logging.getLogger("Server.Logs")

# Generate a secret to validate the auth cookie
SESSION_SECRET = str(uuid.uuid4())


# Bounds for the location fields the GPS form writes.  The /locations
# handlers enforce the same ranges inline.
LATITUDE_LIMITS = (-90.0, 90.0)
LONGITUDE_LIMITS = (-180.0, 180.0)
ALTITUDE_LIMITS = (-1000.0, 10000.0)


def parse_coordinate(value, field_name):
    """Parse a coordinate/measurement field, accepting comma or period decimals."""
    if value is None:
        raise ValueError(_("%s is required") % field_name)
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError:
        raise ValueError(_("%s must be a number") % field_name)


def parse_measurement(value, field_name, limits, default=None):
    """Parse a numeric field and range-check it against ``limits``.

    ``limits`` is any (minimum, maximum) pair — an equipment ``Limits``
    or one of the location tuples above.  A blank field falls back to
    ``default`` when one is given, and is an error otherwise: a value the
    user left empty must not silently become zero.
    """
    if default is not None and (value is None or str(value).strip() == ""):
        return default

    number = parse_coordinate(value, field_name)
    minimum, maximum = limits
    if not minimum <= number <= maximum:
        raise ValueError(
            _("%(field)s must be between %(minimum)s and %(maximum)s")
            % {
                "field": field_name,
                "minimum": format_measurement(minimum),
                "maximum": format_measurement(maximum),
            }
        )
    return number


def parse_name(value, field_name, required=True):
    """Parse and length-check a free-text field, returning it stripped."""
    text = (value or "").strip()
    if required and not text:
        raise ValueError(_("%s is required") % field_name)
    if len(text) > NAME_MAX_LENGTH:
        raise ValueError(
            _("%(field)s must be %(maximum)s characters or fewer")
            % {"field": field_name, "maximum": NAME_MAX_LENGTH}
        )
    return text


def check_equipment_limits(record, limits):
    """Re-check an equipment record's measurements against ``limits``.

    For records that never pass through the edit form — the DeepskyLog
    import — so an upstream value out of range is caught before it is
    written into config rather than at the next boot.
    """
    for field, limit in limits.items():
        parse_measurement(getattr(record, field), field, limit)
    if not record.name.strip():
        raise ValueError(_("%s is required") % _("Name"))


def submitted_eyepiece(form):
    """The raw submitted eyepiece values, keyed as the edit template reads
    them, so a rejected form comes back with what the user typed still in it.
    """
    return {
        "make": form.get("make", ""),
        "name": form.get("name", ""),
        "focal_length_mm": form.get("focal_length_mm", ""),
        "afov": form.get("afov", ""),
        "field_stop": form.get("field_stop", ""),
    }


def submitted_telescope(form):
    """The raw submitted instrument values, keyed as the edit template reads
    them, so a rejected form comes back with what the user typed still in it.
    """
    return {
        "make": form.get("make", ""),
        "name": form.get("name", ""),
        "aperture_mm": form.get("aperture", ""),
        "focal_length_mm": form.get("focal_length_mm", ""),
        "obstruction_perc": form.get("obstruction_perc", ""),
        "mount_type": form.get("mount_type", ""),
        "flip_image": bool(form.get("flip")),
        "flop_image": bool(form.get("flop")),
        "reverse_arrow_a": bool(form.get("reverse_arrow_a")),
        "reverse_arrow_b": bool(form.get("reverse_arrow_b")),
    }


def eyepiece_from_form(form) -> Eyepiece:
    """Build an Eyepiece from submitted form values.

    Raises ValueError — with a message meant for the user — if any field
    is missing, unparseable or out of range.
    """
    return Eyepiece(
        make=parse_name(form.get("make"), _("Make"), required=False),
        name=parse_name(form.get("name"), _("Name")),
        focal_length_mm=parse_measurement(
            form.get("focal_length_mm"),
            _("Focal length"),
            EYEPIECE_LIMITS["focal_length_mm"],
        ),
        afov=parse_measurement(
            form.get("afov"), _("Apparent field of view"), EYEPIECE_LIMITS["afov"]
        ),
        field_stop=parse_measurement(
            form.get("field_stop"),
            _("Field stop"),
            EYEPIECE_LIMITS["field_stop"],
            default=0.0,
        ),
    )


def telescope_from_form(form) -> Telescope:
    """Build a Telescope from submitted form values.

    Raises ValueError — with a message meant for the user — if any field
    is missing, unparseable or out of range.
    """
    mount_type = (form.get("mount_type") or MOUNT_TYPES[0]).strip().lower()
    if mount_type not in MOUNT_TYPES:
        raise ValueError(_("%s is not a valid mount type") % mount_type)

    return Telescope(
        make=parse_name(form.get("make"), _("Make"), required=False),
        name=parse_name(form.get("name"), _("Instrument name")),
        aperture_mm=parse_measurement(
            form.get("aperture"), _("Aperture"), TELESCOPE_LIMITS["aperture_mm"]
        ),
        focal_length_mm=parse_measurement(
            form.get("focal_length_mm"),
            _("Focal length"),
            TELESCOPE_LIMITS["focal_length_mm"],
        ),
        obstruction_perc=parse_measurement(
            form.get("obstruction_perc"),
            _("Obstruction"),
            TELESCOPE_LIMITS["obstruction_perc"],
            default=0.0,
        ),
        mount_type=mount_type,
        flip_image=bool(form.get("flip")),
        flop_image=bool(form.get("flop")),
        reverse_arrow_a=bool(form.get("reverse_arrow_a")),
        reverse_arrow_b=bool(form.get("reverse_arrow_b")),
    )


def auth_required(func):
    def auth_wrapper(*args, **kwargs):
        # check for and validate session
        if "authenticated" in session and session["authenticated"]:
            return func(*args, **kwargs)

        # Pass the original URL via ?next= so Safari preserves it across redirects
        return redirect(f"/login?next={quote(request.url, safe='')}")

    auth_wrapper.__name__ = func.__name__
    return auth_wrapper


class MockSharedState:
    """Mock shared state for standalone testing"""

    def __init__(self):
        self._location = type(
            "Location", (), {"lock": False, "lat": None, "lon": None, "altitude": None}
        )()
        self._screen_img = None
        self._solve_state = False
        self._solution = None

    def location(self):
        return self._location

    def screen(self):
        return self._screen_img

    def solve_state(self):
        return self._solve_state

    def solution(self):
        return self._solution


def server_locale():
    # Try to get from user preferences, session, or accept languages
    # For now, default to English
    return request.accept_languages.best_match(["en", "fr", "de", "es", "zh"]) or "en"


class Server:
    def __init__(
        self,
        keyboard_queue=None,
        ui_queue=None,
        gps_queue=None,
        shared_state=None,
        is_debug=False,
    ):
        self._software_version = utils.get_version()
        self.keyboard_queue = keyboard_queue or multiprocessing.Queue()
        self.ui_queue = ui_queue or multiprocessing.Queue()
        self.gps_queue = gps_queue or multiprocessing.Queue()
        self.shared_state = shared_state or MockSharedState()
        self.ki = KeyboardInterface()
        # gps info
        self.lat = None
        self.lon = None
        self.altitude = None
        self.gps_locked = False

        self.button_dict = {
            "PLUS": self.ki.PLUS,
            "MINUS": self.ki.MINUS,
            "SQUARE": self.ki.SQUARE,
            "LEFT": self.ki.LEFT,
            "UP": self.ki.UP,
            "DOWN": self.ki.DOWN,
            "RIGHT": self.ki.RIGHT,
            "ALT_PLUS": self.ki.ALT_PLUS,
            "ALT_MINUS": self.ki.ALT_MINUS,
            "ALT_LEFT": self.ki.ALT_LEFT,
            "ALT_UP": self.ki.ALT_UP,
            "ALT_DOWN": self.ki.ALT_DOWN,
            "ALT_RIGHT": self.ki.ALT_RIGHT,
            "ALT_0": self.ki.ALT_0,
            "ALT_SQUARE": self.ki.ALT_SQUARE,
            "LNG_LEFT": self.ki.LNG_LEFT,
            "LNG_UP": self.ki.LNG_UP,
            "LNG_DOWN": self.ki.LNG_DOWN,
            "LNG_RIGHT": self.ki.LNG_RIGHT,
            "LNG_SQUARE": self.ki.LNG_SQUARE,
            "POWER_BTN": self.ki.POWER_BTN,
        }

        self.network = sys_utils.Network()

        # Initialize Flask app with absolute template path
        views2_path = os.path.join(os.path.dirname(__file__), "..", "views")
        views2_path = os.path.abspath(views2_path)
        logger.debug(f"Template folder path: {views2_path}")

        app = Flask(__name__, template_folder=views2_path)
        app.secret_key = SESSION_SECRET
        # Register the custom signed integer converter
        app.url_map.converters["signed_int"] = SignedIntConverter

        logger.info(f"Flask app created successfully: {app}")
        logger.info(f"Template folder: {app.template_folder}")

        # Setup Babel for i18n
        Babel(app, locale_selector=server_locale)  # Picked up by app variable

        # Configure Jinja2 environment for i18n
        app.jinja_env.add_extension("jinja2.ext.i18n")

        # Use PiFinder's global gettext function in templates
        import builtins

        app.jinja_env.globals["_"] = builtins._

        # Equipment measurements are floats; render 1000.0 as "1000" so the
        # tables and edit forms read the way the user typed them.
        app.jinja_env.filters["measurement"] = format_measurement
        app.jinja_env.globals["name_max_length"] = NAME_MAX_LENGTH

        # # Create a simple gettext function for templates that works without translation files
        # def simple_gettext(text):
        #     return text

        # def simple_ngettext(singular, plural, n):
        #     return singular if n == 1 else plural

        # app.jinja_env.install_gettext_callables(simple_gettext, simple_ngettext, newstyle=True)

        # # Create a context-safe translation function
        # def translate(text):
        #     try:
        #         from flask_babel import gettext
        #         return gettext(text)
        #     except Exception:
        #         return text

        # # Make translation function available to routes
        # app.jinja_env.globals['_'] = translate

        # Static files routes
        @app.route("/images/<path:filename>")
        def send_image(filename):
            return send_file(
                os.path.join(views2_path, "images", filename), mimetype="image/png"
            )

        @app.route("/js/<path:filename>")
        def send_js(filename):
            return send_file(os.path.join(views2_path, "js", filename))

        @app.route("/css/<path:filename>")
        def send_css(filename):
            return send_file(os.path.join(views2_path, "css", filename))

        @app.route("/")
        def home():
            # logger.debug("/ called")
            # Get version info

            software_version = self._software_version

            # Try to update GPS state
            try:
                self.update_gps()
            except Exception as e:
                logger.error(f"Failed to update GPS in home route: {str(e)}")

            # Use GPS data if available
            lat_text = str(self.lat) if self.gps_locked else ""
            lon_text = str(self.lon) if self.gps_locked else ""
            gps_icon = "gps_fixed" if self.gps_locked else "gps_off"
            gps_text = gettext("Locked") if self.gps_locked else gettext("Not Locked")

            # Default camera values
            ra_text = "0"
            dec_text = "0"
            camera_icon = "broken_image"

            # Try to get solution data
            try:
                if self.shared_state.solve_state() is True:
                    camera_icon = "camera_alt"
                    solution = self.shared_state.solution()
                    if solution and solution.has_pointing():
                        aligned = solution.pointing.aligned.estimate
                        hh, mm, _ = calc_utils.ra_to_hms(aligned.RA)
                        ra_text = f"{hh:02.0f}h{mm:02.0f}m"
                        dec_text = f"{aligned.Dec: .2f}"
            except Exception as e:
                logger.error(f"Failed to get solution data: {str(e)}")

            # Render the template with available data
            return app.jinja_env.get_template("index.html").render(
                title=gettext("Home"),
                software_version=software_version,
                wifi_mode=self.network.wifi_mode(),
                ip=self.network.local_ip(),
                network_name=self.network.get_active_label(),
                gps_icon=gps_icon,
                gps_text=gps_text,
                lat_text=lat_text,
                lon_text=lon_text,
                camera_icon=camera_icon,
                ra_text=ra_text,
                dec_text=dec_text,
            )

        @app.route("/login", methods=["GET", "POST"])
        def login():
            if request.method == "POST":
                password = request.form.get("password")
                # Read from hidden form field (set by GET handler); fall back to session
                origin_url = request.form.get("origin_url") or session.get(
                    "origin_url", "/"
                )
                if sys_utils.verify_password("pifinder", password):
                    session["authenticated"] = True
                    session.pop("origin_url", None)
                    return redirect(origin_url)
                else:
                    return app.jinja_env.get_template("login.html").render(
                        title=gettext("Login"),
                        origin_url=origin_url,
                        error_message=gettext("Invalid Password"),
                    )
            else:
                # Prefer ?next= URL param (set by auth_required); fall back to session
                origin_url = request.args.get("next", session.get("origin_url", "/"))
                return app.jinja_env.get_template("login.html").render(
                    title=gettext("Login"), origin_url=origin_url
                )

        @app.route("/remote")
        @auth_required
        def remote():
            return app.jinja_env.get_template("remote.html").render(title=_("Remote"))

        @app.route("/advanced")
        @auth_required
        def advanced():
            return app.jinja_env.get_template("advanced.html").render(
                title=_("Advanced")
            )

        @app.route("/network")
        @auth_required
        def network_page():
            show_new_form = request.args.get("add_new", 0)

            return app.jinja_env.get_template("network.html").render(
                title=_("Network"),
                net=self.network,
                show_new_form=show_new_form,
            )

        @app.route("/gps")
        @auth_required
        def gps_page():
            self.update_gps()
            show_new_form = request.args.get("add_new", 0)
            logger.debug(
                "/gps: %f, %f, %f ",
                self.lat or 0.0,
                self.lon or 0.0,
                self.altitude or 0.0,
            )

            return app.jinja_env.get_template("gps.html").render(
                title=_("GPS"),
                show_new_form=show_new_form,
                lat=self.lat,
                lon=self.lon,
                altitude=self.altitude,
            )

        @app.route("/gps/update", methods=["POST"])
        @auth_required
        def gps_update():
            lat = request.form.get("latitudeDecimal")
            lon = request.form.get("longitudeDecimal")
            altitude = request.form.get("altitude")
            date_req = request.form.get("date")
            time_req = request.form.get("time")

            try:
                latitude = parse_measurement(lat, _("Latitude"), LATITUDE_LIMITS)
                longitude = parse_measurement(lon, _("Longitude"), LONGITUDE_LIMITS)
                height = parse_measurement(altitude, _("Altitude"), ALTITUDE_LIMITS)
                datetime_utc = None
                if time_req and date_req:
                    try:
                        datetime_obj = timez.parse(
                            f"{date_req} {time_req}", "%Y-%m-%d %H:%M:%S"
                        )
                    except ValueError:
                        raise ValueError(_("Date and time must be YYYY-MM-DD h:m:s"))
                    datetime_utc = datetime_obj.replace(tzinfo=timezone.utc)
            except ValueError as e:
                # Re-render with what was typed, the way /locations does.
                return app.jinja_env.get_template("gps.html").render(
                    title=_("GPS"),
                    show_new_form=0,
                    lat=lat,
                    lon=lon,
                    altitude=altitude,
                    error_message=str(e),
                )

            gps_lock(latitude, longitude, height)
            if datetime_utc is not None:
                time_lock(datetime_utc)
            logger.debug(
                "GPS update: %s, %s, %s, %s, %s", lat, lon, altitude, date_req, time_req
            )
            time.sleep(1)  # give the gps thread a chance to update
            return redirect("/")

        @app.route("/locations")
        @auth_required
        def locations_page():
            show_new_form = request.args.get("add_new", 0)
            cfg = config.Config()
            cfg.load_config()  # Ensure config is loaded
            return app.jinja_env.get_template("locations.html").render(
                title=_("Locations"),
                locations=cfg.locations.locations,
                show_new_form=show_new_form,
            )

        @app.route("/locations/add", methods=["POST"])
        @auth_required
        def location_add():
            try:
                name = (request.form.get("name") or "").strip()
                lat = parse_coordinate(request.form.get("latitude"), _("Latitude"))
                lon = parse_coordinate(request.form.get("longitude"), _("Longitude"))
                altitude = parse_coordinate(request.form.get("altitude"), _("Altitude"))
                error_in_m = parse_coordinate(
                    request.form.get("error_in_m", "0"), _("Error")
                )
                source = request.form.get("source", "Manual Entry")

                # Server-side validation
                if not name:
                    raise ValueError(_("Location name is required"))
                if not (-90 <= lat <= 90):
                    raise ValueError(_("Latitude must be between -90 and 90"))
                if not (-180 <= lon <= 180):
                    raise ValueError(_("Longitude must be between -180 and 180"))
                if not (-1000 <= altitude <= 10000):
                    raise ValueError(
                        _("Altitude must be between -1000 and 10000 meters")
                    )
                if not (0 <= error_in_m <= 10000):
                    raise ValueError(_("Error must be between 0 and 10000 meters"))

                from PiFinder.locations import Location

                new_location = Location(
                    name=name,
                    latitude=lat,
                    longitude=lon,
                    height=altitude,
                    error_in_m=error_in_m,
                    source=source,
                )

                cfg = config.Config()
                cfg.load_config()
                cfg.locations.add_location(new_location)
                cfg.save_locations()

                self.ui_queue.put("reload_config")
                return redirect("/locations")

            except ValueError as e:
                return app.jinja_env.get_template("locations.html").render(
                    title=_("Locations"),
                    locations=config.Config().locations.locations,
                    show_new_form=1,
                    error_message=str(e),
                )

        @app.route("/locations/rename/<int:location_id>", methods=["POST"])
        @auth_required
        def location_rename(location_id):
            try:
                cfg = config.Config()
                cfg.load_config()

                if not (0 <= location_id < len(cfg.locations.locations)):
                    raise ValueError("Invalid location ID")

                name = (request.form.get("name") or "").strip()
                lat = parse_coordinate(request.form.get("latitude"), _("Latitude"))
                lon = parse_coordinate(request.form.get("longitude"), _("Longitude"))
                altitude = parse_coordinate(request.form.get("altitude"), _("Altitude"))
                error_in_m = parse_coordinate(
                    request.form.get("error_in_m", "0"), _("Error")
                )
                source = request.form.get("source", "Manual Entry")

                # Server-side validation
                if not name:
                    raise ValueError(_("Location name is required"))
                if not (-90 <= lat <= 90):
                    raise ValueError(_("Latitude must be between -90 and 90"))
                if not (-180 <= lon <= 180):
                    raise ValueError(_("Longitude must be between -180 and 180"))
                if not (-1000 <= altitude <= 10000):
                    raise ValueError(
                        _("Altitude must be between -1000 and 10000 meters")
                    )
                if not (0 <= error_in_m <= 10000):
                    raise ValueError(_("Error must be between 0 and 10000 meters"))

                location = cfg.locations.locations[location_id]
                location.name = name
                location.latitude = lat
                location.longitude = lon
                location.height = altitude
                location.error_in_m = error_in_m
                location.source = source

                cfg.save_locations()
                self.ui_queue.put("reload_config")
                return redirect("/locations")

            except ValueError as e:
                return app.jinja_env.get_template("locations.html").render(
                    title=_("Locations"),
                    locations=config.Config().locations.locations,
                    show_new_form=0,
                    error_message=str(e),
                )

        @app.route("/locations/delete/<int:location_id>")
        @auth_required
        def location_delete(location_id):
            cfg = config.Config()
            cfg.load_config()
            if 0 <= location_id < len(cfg.locations.locations):
                location = cfg.locations.locations[location_id]
                cfg.locations.remove_location(location)
                cfg.save_locations()
                # Notify main process to reload config
                self.ui_queue.put("reload_config")
            return redirect("/locations")

        @app.route("/locations/set_default/<int:location_id>")
        @auth_required
        def location_set_default(location_id):
            cfg = config.Config()
            cfg.load_config()
            if 0 <= location_id < len(cfg.locations.locations):
                location = cfg.locations.locations[location_id]
                cfg.locations.set_default(location)
                cfg.save_locations()
                # Notify main process to reload config
                self.ui_queue.put("reload_config")
            return redirect("/locations")

        @app.route("/locations/load/<int:location_id>")
        @auth_required
        def location_load(location_id):
            cfg = config.Config()
            cfg.load_config()  # Ensure config is loaded
            if 0 <= location_id < len(cfg.locations.locations):
                location = cfg.locations.locations[location_id]
                gps_lock(location.latitude, location.longitude, location.height)
            return redirect("/locations")

        @app.route("/network/add", methods=["POST"])
        @auth_required
        def network_add():
            ssid = request.form.get("ssid")
            psk = request.form.get("psk")
            if len(psk) < 8:
                key_mgmt = "NONE"
            else:
                key_mgmt = "WPA-PSK"

            self.network.add_wifi_network(ssid, key_mgmt, psk)
            return redirect("/network")

        @app.route("/network/delete/<int:network_id>")
        @auth_required
        def network_delete(network_id):
            self.network.delete_wifi_network(network_id)
            return redirect("/network")

        @app.route("/network/update", methods=["POST"])
        @auth_required
        def network_update():
            wifi_mode = request.form.get("wifi_mode")
            ap_name = request.form.get("ap_name")
            host_name = request.form.get("host_name")

            self.network.set_wifi_mode(wifi_mode)
            self.network.set_ap_name(ap_name)
            self.network.set_host_name(host_name)

            applied_host = self.network.get_host_name()
            return app.jinja_env.get_template("network.html").render(
                title=_("Network"),
                net=self.network,
                show_new_form=0,
                status_message=_(
                    "Network settings updated — no restart needed. This device is "
                    "now reachable at http://{host}.local. If you changed the host "
                    "name, the previous address stops working, so reconnect there."
                ).format(host=applied_host),
            )

        @app.route("/tools/pwchange", methods=["POST"])
        @auth_required
        def password_change():
            current_password = request.form.get("current_password")
            new_passworda = request.form.get("new_passworda")
            new_passwordb = request.form.get("new_passwordb")

            if new_passworda == "" or current_password == "" or new_passwordb == "":
                return app.jinja_env.get_template("tools.html").render(
                    title=_("Tools"),
                    error_message=_("You must fill in all password fields"),
                )

            if new_passworda == new_passwordb:
                if sys_utils.change_password(
                    "pifinder", current_password, new_passworda
                ):
                    return app.jinja_env.get_template("tools.html").render(
                        title=_("Tools"), status_message=_("Password Changed")
                    )
                else:
                    return app.jinja_env.get_template("tools.html").render(
                        title=_("Tools"), error_message=_("Incorrect current password")
                    )
            else:
                return app.jinja_env.get_template("tools.html").render(
                    title=_("Tools"), error_message=_("New passwords do not match")
                )

        @app.route("/system/restart")
        @auth_required
        def system_restart():
            """
            Restarts the RPI system
            """
            sys_utils.restart_system()
            return "restarting"

        @app.route("/system/restart_pifinder")
        @auth_required
        def pifinder_restart():
            """
            Restarts just the PiFinder software
            """
            sys_utils.restart_pifinder()
            return "restarting"

        @app.route("/equipment")
        @auth_required
        def equipment():
            return app.jinja_env.get_template("equipment.html").render(
                title=_("Equipment"), equipment=config.Config().equipment
            )

        def equipment_page_error(message):
            """Render the equipment page with an error instead of raising.

            A hand-edited or stale URL carrying an index nobody owns used
            to reach the list and raise IndexError as a 500.
            """
            return app.jinja_env.get_template("equipment.html").render(
                title=_("Equipment"),
                equipment=config.Config().equipment,
                error_message=message,
            )

        @app.route("/equipment/set_active_instrument/<int:instrument_id>")
        @auth_required
        def set_active_instrument(instrument_id: int):
            cfg = config.Config()
            if not 0 <= instrument_id < len(cfg.equipment.telescopes):
                return equipment_page_error(_("No such instrument"))
            cfg.equipment.set_active_telescope(cfg.equipment.telescopes[instrument_id])
            cfg.save_equipment()
            self.ui_queue.put("reload_config")
            return app.jinja_env.get_template("equipment.html").render(
                title=_("Equipment"),
                equipment=cfg.equipment,
                success_message=cfg.equipment.active_telescope.make
                + " "
                + cfg.equipment.active_telescope.name
                + " "
                + _("set as active instrument."),
            )

        @app.route("/equipment/set_active_eyepiece/<int:eyepiece_id>")
        @auth_required
        def set_active_eyepiece(eyepiece_id: int):
            cfg = config.Config()
            if not 0 <= eyepiece_id < len(cfg.equipment.eyepieces):
                return equipment_page_error(_("No such eyepiece"))
            cfg.equipment.set_active_eyepiece(cfg.equipment.eyepieces[eyepiece_id])
            cfg.save_equipment()
            self.ui_queue.put("reload_config")
            return app.jinja_env.get_template("equipment.html").render(
                title=_("Equipment"),
                equipment=cfg.equipment,
                success_message=cfg.equipment.active_eyepiece.make
                + " "
                + cfg.equipment.active_eyepiece.name
                + " "
                + _("set as active eyepiece."),
            )

        @app.route("/equipment/import_from_deepskylog", methods=["POST"])
        @auth_required
        def equipment_import():
            username = request.form.get("dsl_name")
            cfg = config.Config()
            skipped = 0
            if username:
                instruments = pds.dsl_instruments(username)
                for instrument in instruments:
                    if instrument["type"] == 0:
                        # Skip the naked eye
                        continue

                    try:
                        make = instrument["instrument_make"]["name"]

                        obstruction_perc = instrument["obstruction_perc"]
                        if obstruction_perc is None:
                            obstruction_perc = 0

                        # Convert the html special characters (ampersand, quote, ...) in instrument["name"]
                        # to the corresponding character
                        instrument["name"] = instrument["name"].replace("&amp;", "&")
                        instrument["name"] = instrument["name"].replace("&quot;", '"')
                        instrument["name"] = instrument["name"].replace("&apos;", "'")
                        instrument["name"] = instrument["name"].replace("&lt;", "<")
                        instrument["name"] = instrument["name"].replace("&gt;", ">")

                        new_instrument = Telescope(
                            make=make,
                            name=instrument["name"],
                            aperture_mm=float(instrument["diameter"]),
                            focal_length_mm=float(
                                instrument["diameter"] * instrument["fd"]
                            ),
                            obstruction_perc=float(obstruction_perc),
                            mount_type=instrument["mount_type"]["name"].lower(),
                            flip_image=bool(instrument["flip_image"]),
                            flop_image=bool(instrument["flop_image"]),
                            reverse_arrow_a=False,
                            reverse_arrow_b=False,
                        )
                        check_equipment_limits(new_instrument, TELESCOPE_LIMITS)
                    except (ValueError, TypeError, KeyError) as e:
                        # An upstream record we can't make sense of is
                        # skipped, not written through into config.
                        logger.warning("Skipping DeepskyLog instrument: %s", e)
                        skipped += 1
                        continue

                    try:
                        cfg.equipment.telescopes.index(new_instrument)
                    except ValueError:
                        cfg.equipment.telescopes.append(new_instrument)

                # Add the eyepieces from deepskylog
                eyepieces = pds.dsl_eyepieces(username)
                for eyepiece in eyepieces:
                    try:
                        # Convert the html special characters (ampersand, quote, ...) in eyepiece["name"]
                        # to the corresponding character
                        eyepiece["name"] = eyepiece["name"].replace("&amp;", "&")
                        eyepiece["name"] = eyepiece["name"].replace("&quot;", '"')
                        eyepiece["name"] = eyepiece["name"].replace("&apos;", "'")
                        eyepiece["name"] = eyepiece["name"].replace("&lt;", "<")
                        eyepiece["name"] = eyepiece["name"].replace("&gt;", ">")

                        make = eyepiece["eyepiece_make"]["name"]

                        new_eyepiece = Eyepiece(
                            make=make,
                            name=eyepiece["name"],
                            focal_length_mm=float(eyepiece["focalLength"]),
                            afov=float(eyepiece["apparentFOV"]),
                            field_stop=float(eyepiece["field_stop_mm"]),
                        )
                        check_equipment_limits(new_eyepiece, EYEPIECE_LIMITS)
                    except (ValueError, TypeError, KeyError) as e:
                        logger.warning("Skipping DeepskyLog eyepiece: %s", e)
                        skipped += 1
                        continue

                    try:
                        cfg.equipment.eyepieces.index(new_eyepiece)
                    except ValueError:
                        cfg.equipment.add_eyepiece(new_eyepiece)

                cfg.save_equipment()
                self.ui_queue.put("reload_config")

            success_message = _(
                "Equipment Imported, restart your PiFinder to use this new data"
            )
            if skipped:
                success_message += " " + _(
                    "%s entries were skipped because DeepskyLog had no usable values for them."
                ) % str(skipped)
            return app.jinja_env.get_template("equipment.html").render(
                title=_("Equipment"),
                equipment=config.Config().equipment,
                success_message=success_message,
            )

        @app.route("/equipment/edit_eyepiece/<signed_int:eyepiece_id>")
        @auth_required
        def edit_eyepiece(eyepiece_id: int):
            eyepieces = config.Config().equipment.eyepieces
            if eyepiece_id >= 0:
                if eyepiece_id >= len(eyepieces):
                    return equipment_page_error(_("No such eyepiece"))
                eyepiece = eyepieces[eyepiece_id]
            else:
                # A new eyepiece starts blank rather than pre-filled with
                # zeros, which are not values any eyepiece may keep.
                eyepiece = submitted_eyepiece({})

            return app.jinja_env.get_template("edit_eyepiece.html").render(
                title=_("Edit Eyepiece"),
                eyepiece=eyepiece,
                eyepiece_id=eyepiece_id,
                limits=EYEPIECE_LIMITS,
            )

        @app.route("/equipment/add_eyepiece/<signed_int:eyepiece_id>", methods=["POST"])
        @auth_required
        def equipment_add_eyepiece(eyepiece_id: int):
            cfg = config.Config()

            try:
                eyepiece = eyepiece_from_form(request.form)
            except ValueError as e:
                # Hand the form back with the message and the values the
                # user typed, rather than claiming the save worked.
                return app.jinja_env.get_template("edit_eyepiece.html").render(
                    title=_("Edit Eyepiece"),
                    eyepiece=submitted_eyepiece(request.form),
                    eyepiece_id=eyepiece_id,
                    limits=EYEPIECE_LIMITS,
                    error_message=str(e),
                )

            try:
                if eyepiece_id >= 0:
                    cfg.equipment.eyepieces[eyepiece_id] = eyepiece
                else:
                    try:
                        index = cfg.equipment.eyepieces.index(eyepiece)
                        cfg.equipment.update_eyepiece(index, eyepiece)
                    except ValueError:
                        cfg.equipment.eyepieces.append(eyepiece)

                cfg.save_equipment()
                self.ui_queue.put("reload_config")
            except Exception as e:
                logger.exception("Error adding eyepiece")
                return app.jinja_env.get_template("equipment.html").render(
                    title=_("Equipment"),
                    equipment=config.Config().equipment,
                    error_message=_("Could not save eyepiece: %s") % e,
                )

            return app.jinja_env.get_template("equipment.html").render(
                title=_("Equipment"),
                equipment=config.Config().equipment,
                success_message=_("Eyepiece added, restart your PiFinder to use"),
            )

        @app.route("/equipment/delete_eyepiece/<int:eyepiece_id>")
        @auth_required
        def equipment_delete_eyepiece(eyepiece_id: int):
            cfg = config.Config()
            if not 0 <= eyepiece_id < len(cfg.equipment.eyepieces):
                return equipment_page_error(_("No such eyepiece"))
            cfg.equipment.eyepieces.pop(eyepiece_id)
            cfg.save_equipment()
            self.ui_queue.put("reload_config")
            return app.jinja_env.get_template("equipment.html").render(
                title=_("Equipment"),
                equipment=config.Config().equipment,
                success_message=_(
                    "Eyepiece Deleted, restart your PiFinder to remove from menu"
                ),
            )

        @app.route("/equipment/edit_instrument/<signed_int:instrument_id>")
        @auth_required
        def edit_instrument(instrument_id: int):
            telescopes = config.Config().equipment.telescopes
            if instrument_id >= 0:
                if instrument_id >= len(telescopes):
                    return equipment_page_error(_("No such instrument"))
                telescope = telescopes[instrument_id]
            else:
                # A new instrument starts blank rather than pre-filled with
                # zeros, which are not values any instrument may keep.
                telescope = submitted_telescope({"mount_type": MOUNT_TYPES[0]})

            return app.jinja_env.get_template("edit_instrument.html").render(
                title=_("Edit Instrument"),
                telescope=telescope,
                instrument_id=instrument_id,
                limits=TELESCOPE_LIMITS,
            )

        @app.route(
            "/equipment/add_instrument/<signed_int:instrument_id>", methods=["POST"]
        )
        @auth_required
        def equipment_add_instrument(instrument_id: int):
            cfg = config.Config()

            try:
                instrument = telescope_from_form(request.form)
            except ValueError as e:
                # Hand the form back with the message and the values the
                # user typed, rather than claiming the save worked.
                return app.jinja_env.get_template("edit_instrument.html").render(
                    title=_("Edit Instrument"),
                    telescope=submitted_telescope(request.form),
                    instrument_id=instrument_id,
                    limits=TELESCOPE_LIMITS,
                    error_message=str(e),
                )

            try:
                if instrument_id >= 0:
                    cfg.equipment.telescopes[instrument_id] = instrument
                else:
                    try:
                        index = cfg.equipment.telescopes.index(instrument)
                        cfg.equipment.telescopes[index] = instrument
                    except ValueError:
                        cfg.equipment.telescopes.append(instrument)

                cfg.save_equipment()
                self.ui_queue.put("reload_config")
            except Exception as e:
                logger.exception("Error adding instrument")
                return app.jinja_env.get_template("equipment.html").render(
                    title=_("Equipment"),
                    equipment=config.Config().equipment,
                    error_message=_("Could not save instrument: %s") % e,
                )

            return app.jinja_env.get_template("equipment.html").render(
                title=_("Equipment"),
                equipment=config.Config().equipment,
                success_message=_("Instrument Added, restart your PiFinder to use"),
            )

        @app.route("/equipment/delete_instrument/<int:instrument_id>")
        @auth_required
        def equipment_delete_instrument(instrument_id: int):
            cfg = config.Config()
            if not 0 <= instrument_id < len(cfg.equipment.telescopes):
                return equipment_page_error(_("No such instrument"))
            cfg.equipment.telescopes.pop(instrument_id)
            cfg.save_equipment()
            self.ui_queue.put("reload_config")
            return app.jinja_env.get_template("equipment.html").render(
                title=_("Equipment"),
                equipment=config.Config().equipment,
                success_message=_(
                    "Instrument Deleted, restart your PiFinder to remove from menu"
                ),
            )

        @app.route("/observations")
        @auth_required
        def obs_sessions():
            obs_db = ObservationsDatabase()
            if request.args.get("download", 0) == "1":
                # Download all as TSV
                observations = obs_db.observations_as_tsv()

                response = make_response(observations)
                response.headers["Content-Disposition"] = (
                    "attachment; filename=observations.tsv"
                )
                response.headers["Content-Type"] = "text/tsv"
                return response

            # regular html page of sessions
            sessions = obs_db.get_sessions()
            metadata = {
                "sess_count": len(sessions),
                "object_count": sum(x["observations"] for x in sessions),
                "total_duration": sum(x["duration"] for x in sessions),
            }
            return app.jinja_env.get_template("obs_sessions.html").render(
                title=_("Observations"), sessions=sessions, metadata=metadata
            )

        @app.route("/observations/<session_id>")
        @auth_required
        def obs_session(session_id):
            obs_db = ObservationsDatabase()
            if request.args.get("download", 0) == "1":
                # Download all as TSV
                observations = obs_db.observations_as_tsv(session_id)

                response = make_response(observations)
                response.headers["Content-Disposition"] = (
                    f"attachment; filename=observations_{session_id}.tsv"
                )
                response.headers["Content-Type"] = "text/tsv"
                return response

            session = obs_db.get_sessions(session_id)[0]
            objects = obs_db.get_logs_by_session(session_id)
            ret_objects = []
            for obj in objects:
                obj_ = dict(obj)
                obj_notes = json.loads(obj_["notes"])
                obj_["notes"] = "<br>".join(
                    [f"{key}: {value}" for key, value in obj_notes.items()]
                )
                ret_objects.append(obj_)
            return app.jinja_env.get_template("obs_session_log.html").render(
                title=_("Session Log"), session=session, objects=ret_objects
            )

        @app.route("/tools")
        @auth_required
        def tools():
            return app.jinja_env.get_template("tools.html").render(title=_("Tools"))

        @app.route("/logs")
        @auth_required
        def logs_page():
            return app.jinja_env.get_template("logs.html").render(title=_("Logs"))

        @app.route("/logs/stream")
        @auth_required
        def stream_logs():
            import time

            TAIL_BYTES = 100 * 1024  # serve only the last 100 KB on first load
            t0 = time.monotonic()
            try:
                position = int(request.args.get("position", 0))
                log_file = os.path.expanduser("~/PiFinder_data/pifinder.log")

                try:
                    file_size = os.path.getsize(log_file)
                    logs_logger.debug(
                        "stream_logs: position=%d file_size=%d", position, file_size
                    )

                    # Reset when file shrank (rotation) or on first call; tail large files.
                    if position > file_size or position == 0:
                        position = max(0, file_size - TAIL_BYTES)

                    t1 = time.monotonic()
                    with open(log_file, "r") as f:
                        f.seek(position)
                        new_lines = f.readlines()
                        new_position = f.tell()
                    logs_logger.debug(
                        "stream_logs: read %d lines (%d bytes) in %.3fs",
                        len(new_lines),
                        new_position - position,
                        time.monotonic() - t1,
                    )

                    if new_position - position > 1024 * 1024:
                        logs_logger.warning(
                            "stream_logs: large response %.1f MB",
                            (new_position - position) / 1e6,
                        )

                    if new_lines:
                        return jsonify({"logs": new_lines, "position": new_position})
                    else:
                        return jsonify({"logs": [], "position": new_position})
                except FileNotFoundError:
                    logger.error(f"Log file not found: {log_file}")
                    return jsonify({"logs": [], "position": 0, "file_not_found": True})

            except Exception as e:
                logger.error(f"Error streaming logs: {e}")
                return jsonify({"logs": [], "position": position})
            finally:
                logger.debug("stream_logs: total %.3fs", time.monotonic() - t0)

        @app.route("/logs/download")
        @auth_required
        def download_logs():
            import zipfile
            import tempfile

            try:
                # Create a temporary zip file
                timestamp = timez.local_now().strftime("%Y%m%d_%H%M%S")

                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".zip"
                ) as temp_file:
                    zip_path = temp_file.name

                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                    # Add all log files
                    log_dir = os.path.expanduser("~/PiFinder_data")
                    for filename in os.listdir(log_dir):
                        if filename.startswith("pifinder") and filename.endswith(
                            ".log"
                        ):
                            file_path = os.path.join(log_dir, filename)
                            zipf.write(file_path, filename)

                # Send the zip file
                def remove_file(response):
                    try:
                        os.remove(zip_path)
                    except Exception:
                        pass
                    return response

                return send_file(
                    zip_path,
                    as_attachment=True,
                    download_name=f"logs_{timestamp}.zip",
                    mimetype="application/zip",
                )

            except Exception as e:
                logger.error(f"Error creating log zip: {e}")
                return app.jinja_env.get_template("logs.html").render(
                    title=_("Logs"), error_message=_("Error creating log archive")
                )

        @app.route("/logs/configs")
        @auth_required
        def list_log_configs():
            """Return all available logconf_*.json presets with display names."""
            active = utils.active_logconf_name()
            configs = []
            for name in utils.available_logconfs():
                stem = name[len("logconf_") : -len(".json")]
                configs.append(
                    {
                        "file": name,
                        "name": stem.replace("_", " ").title(),
                        "active": name == active,
                    }
                )
            return jsonify({"configs": configs})

        @app.route("/logs/switch_config", methods=["POST"])
        @auth_required
        def switch_log_config():
            """Persist the chosen log config to the data dir, then restart."""
            logconf_file = request.form.get("logconf_file", "").strip()
            try:
                utils.set_active_logconf(logconf_file)
                logger.info("Switched log config to %s", logconf_file)
            except (ValueError, FileNotFoundError):
                return jsonify(
                    {"status": "error", "message": "Invalid log config file name"}
                )
            except Exception as e:
                logger.error("Failed to switch log config: %s", e)
                return jsonify({"status": "error", "message": str(e)})
            return app.jinja_env.get_template("restart_pifinder.html").render(
                title=_("Restarting PiFinder")
            )

        @app.route("/logs/upload_config", methods=["POST"])
        @auth_required
        def upload_log_config():
            """Upload a new logconf_*.json file."""
            upload = request.files.get("config_file")
            if not upload:
                logger.warning("No file provided for log config upload")
                return jsonify({"status": "error", "message": "No file provided"})
            filename = upload.filename
            if not filename.startswith("logconf_") or not filename.endswith(".json"):
                logger.warning("Invalid log config file name: %s", filename)
                return jsonify(
                    {
                        "status": "error",
                        "message": "File must be named logconf_<name>.json",
                    }
                )
            if os.path.exists(filename):
                logger.warning("Log config file already exists: %s", filename)
                return jsonify(
                    {
                        "status": "error",
                        "message": f"File already exists: {filename}",
                    }
                )
            try:
                upload.save(filename)
                logger.info("Uploaded log config: %s", filename)
                return jsonify({"status": "ok", "file": filename})
            except Exception as e:
                logger.error("Failed to save uploaded log config: %s", e)
                return jsonify({"status": "error", "message": str(e)})

        @app.route("/data")
        @auth_required
        def data_page():
            return app.jinja_env.get_template("data.html").render(
                title=_("Data"),
                start_path=request.args.get("path", ""),
                start_pattern=request.args.get("pattern", ""),
            )

        def data_error(exc, status=400):
            return jsonify({"status": "error", "message": str(exc)}), status

        @app.route("/data/api/list")
        @auth_required
        def data_list():
            try:
                root = data_browser.data_root()
                listing = data_browser.list_dir(
                    root,
                    request.args.get("path", ""),
                    request.args.get("pattern", ""),
                )
                listing["shortcuts"] = data_browser.shortcuts(root)
                listing["status"] = "ok"
                return jsonify(listing)
            except data_browser.DataPathError as e:
                return data_error(e, 404)

        @app.route("/data/api/mkdir", methods=["POST"])
        @auth_required
        def data_mkdir():
            body = request.get_json(silent=True) or {}
            try:
                new_path = data_browser.make_dir(
                    data_browser.data_root(),
                    body.get("path", ""),
                    body.get("name", ""),
                )
                return jsonify({"status": "ok", "path": new_path})
            except (data_browser.DataPathError, OSError) as e:
                return data_error(e)

        @app.route("/data/api/upload", methods=["POST"])
        @auth_required
        def data_upload():
            rel_path = request.form.get("path", "")
            files = request.files.getlist("files")
            if not files:
                return data_error(_("No file provided"))
            saved = []
            try:
                for upload in files:
                    saved.append(
                        data_browser.save_upload(
                            data_browser.data_root(),
                            rel_path,
                            upload.filename or "",
                            upload.stream,
                        )
                    )
            except (data_browser.DataPathError, OSError) as e:
                logger.warning("Data upload failed: %s", e)
                return data_error(e)
            logger.info("Data upload: %s", ", ".join(saved))
            return jsonify({"status": "ok", "saved": saved})

        @app.route("/data/api/delete", methods=["POST"])
        @auth_required
        def data_delete():
            body = request.get_json(silent=True) or {}
            paths = body.get("paths")
            if paths is None:
                paths = [body.get("path", "")]
            deleted = []
            try:
                for rel_path in paths:
                    data_browser.delete(data_browser.data_root(), rel_path)
                    deleted.append(rel_path)
            except (data_browser.DataPathError, OSError) as e:
                logger.warning("Data delete failed: %s", e)
                return data_error(e)
            logger.info("Data delete: %s", ", ".join(deleted))
            return jsonify({"status": "ok", "deleted": deleted})

        @app.route("/data/api/view")
        @auth_required
        def data_view():
            try:
                result = data_browser.read_text(
                    data_browser.data_root(), request.args.get("path", "")
                )
                result["status"] = "ok"
                return jsonify(result)
            except data_browser.DataPathError as e:
                return data_error(e, 404)

        @app.route("/data/download")
        @auth_required
        def data_download():
            rel_path = request.args.get("path", "")
            root = data_browser.data_root()
            try:
                target = data_browser.resolve(root, rel_path)
                if target.is_dir():
                    zip_file, name = data_browser.zip_dir(root, rel_path)
                    return send_file(
                        zip_file,
                        as_attachment=True,
                        download_name=name,
                        mimetype="application/zip",
                    )
                file_path = data_browser.file_for_download(root, rel_path)
                return send_file(
                    file_path, as_attachment=True, download_name=file_path.name
                )
            except data_browser.DataPathError as e:
                return data_error(e, 404)

        @app.route("/tools/backup")
        @auth_required
        def tools_backup():
            _backup_file = sys_utils.backup_userdata()

            # Assumes the standard backup location
            return send_file(
                os.path.expanduser("~/PiFinder_data/PiFinder_backup.zip"),
                as_attachment=True,
            )

        @app.route("/tools/restore", methods=["POST"])
        @auth_required
        def tools_restore():
            sys_utils.remove_backup()
            backup_file = request.files.get("backup_file")
            if backup_file:
                backup_file.save(
                    os.path.expanduser("~/PiFinder_data/PiFinder_backup.zip")
                )

                sys_utils.restore_userdata(
                    os.path.expanduser("~/PiFinder_data/PiFinder_backup.zip")
                )

            return app.jinja_env.get_template("restart_pifinder.html").render(
                title=_("Restart PiFinder")
            )

        @app.route("/key_callback", methods=["POST"])
        @auth_required
        def key_callback():
            button = request.json.get("button")
            if button in self.button_dict:
                self.key_callback(self.button_dict[button])
            else:
                self.key_callback(int(button))
            return jsonify({"message": "success"})

        @app.route("/api/current-selection")
        @auth_required
        def current_selection():
            """
            Returns information about the currently active UI item for testing purposes
            """
            try:
                ui_state_data = self.shared_state.current_ui_state()
                if ui_state_data is None:
                    return jsonify({"error": "UI state not available"})

                return jsonify(ui_state_data)

            except Exception as e:
                logger.error(f"Error getting current UI state: {e}")
                return jsonify({"error": str(e)})

        @app.route("/image")
        def serve_pil_image():
            empty_img = Image.new(
                "RGB", (60, 30), color=(73, 109, 137)
            )  # create an image using PIL
            img = None
            try:
                img = self.shared_state.screen()
            except (BrokenPipeError, EOFError):
                pass

            if img is None:
                img = empty_img
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format="PNG")  # adjust for your image format
            img_byte_arr.seek(0)

            return send_file(img_byte_arr, mimetype="image/png")

        # # If you want to see a log of all requests for debugging, you can uncomment this:
        # @app.after_request
        # def log_request(response):
        #     logger.debug(
        #         "%s %s %s", request.method, request.path, response.status_code
        #     )
        #     return response

        try:
            from PiFinder.api_extensions import register_api_routes

            register_api_routes(app, self, require_auth=False)
        except Exception:
            logger.exception("Failed to register API extension routes")

        @auth_required
        def gps_lock(lat: float = 50, lon: float = 3, altitude: float = 10):
            msg = (
                "fix",
                {
                    "lat": lat,
                    "lon": lon,
                    "altitude": altitude,
                    "error_in_m": 0,
                    "source": "WEB",
                    "lock": True,
                },
            )
            self.gps_queue.put(msg)
            logger.debug("Putting location msg on gps_queue: {msg}")

        def time_lock(time=timez.local_now()):
            msg = ("time", time)
            self.gps_queue.put(msg)
            logger.debug("Putting time msg on gps_queue: {msg}")

        # Store the app reference for running
        self.app = app

    def run(self):
        # If the PiFinder software is running as a service
        # it can grab port 80.  If not, it needs to use 8080
        try:
            waitress_serve(self.app, host="0.0.0.0", port=80)
            logger.info("Webserver started on port 80")
        except (PermissionError, OSError) as e:
            logger.debug(f"Permission denied on port 80, trying 8080. {e}")
            try:
                waitress_serve(self.app, host="0.0.0.0", port=8080)
                logger.info("Webserver started on port 8080")
            except Exception as e2:
                logger.exception(f"Failed to start server on port 8080. {e2}")
                raise
        logger.debug("Webserver is running")

    def key_callback(self, key):
        self.keyboard_queue.put(key)

    def update_gps(self):
        """Update GPS information"""
        location = self.shared_state.location()

        if location.lock is True:
            self.gps_locked = True
            self.lat = location.lat
            self.lon = location.lon
            self.altitude = location.altitude
        else:
            self.gps_locked = False
            self.lat = None
            self.lon = None
            self.altitude = None


def run_server(
    keyboard_queue, ui_queue, gps_queue, shared_state, log_queue, verbose=False
):
    MultiprocLogging.configurer(log_queue)
    server = Server(keyboard_queue, ui_queue, gps_queue, shared_state, verbose)
    server.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="PiFinder Flask Web Server with i18n support"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--port", type=int, default=8080, help="Port to run server on (default: 8080)"
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)"
    )

    args = parser.parse_args()

    # Setup basic logging for standalone mode
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(name)s:%(levelname)s:%(message)s",
    )

    logger.info("Starting PiFinder Server in standalone mode")

    # Create a single queue for command line testing
    test_queue: multiprocessing.Queue = multiprocessing.Queue()

    # Create server with mock components
    server = Server(
        keyboard_queue=test_queue,
        ui_queue=test_queue,
        gps_queue=test_queue,
        shared_state=MockSharedState(),
        is_debug=args.debug,
    )

    # Override the default port behavior for command line usage
    try:
        logger.info("Starting web server.")
        server.run()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server failed to start: {e}")
        sys.exit(1)
