import io
import json
import logging
import time
import uuid
import os
import argparse
import sys
import multiprocessing
from datetime import datetime, timezone

import pydeepskylog as pds
from PIL import Image
from PiFinder import utils, calc_utils, config
from PiFinder.db.observations_db import (
    ObservationsDatabase,
)
from PiFinder.equipment import Telescope, Eyepiece
from PiFinder.keyboard_interface import KeyboardInterface

from flask import Flask, request, jsonify, send_file, redirect, session, make_response
from flask_babel import Babel, gettext  # type: ignore[import-untyped]

from PiFinder import i18n  # noqa: F401

# Type annotation for the global _ function installed by gettext.install()
import builtins

_ = builtins._  # type: ignore[attr-defined]


sys_utils = utils.get_sys_utils()

logger = logging.getLogger("Server")

# Generate a secret to validate the auth cookie
SESSION_SECRET = str(uuid.uuid4())


def auth_required(func):
    def auth_wrapper(*args, **kwargs):
        # check for and validate session
        if "authenticated" in session and session["authenticated"]:
            return func(*args, **kwargs)

        # Store the original URL for redirect after login
        session["origin_url"] = request.url
        return redirect("/login")

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


def server2_locale():
    # Try to get from user preferences, session, or accept languages
    # For now, default to English
    return request.accept_languages.best_match(["en", "fr", "de", "es"]) or "en"


class Server2:
    def __init__(
        self,
        keyboard_queue=None,
        ui_queue=None,
        gps_queue=None,
        shared_state=None,
        is_debug=False,
    ):
        self.version_txt = f"{utils.pifinder_dir}/version.txt"
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

        button_dict = {
            "UP": self.ki.PLUS,
            "DN": self.ki.MINUS,
            "SQUARE": self.ki.SQUARE,
            "A": self.ki.LEFT,
            "B": self.ki.UP,
            "C": self.ki.DOWN,
            "D": self.ki.RIGHT,
            "ALT_PLUS": self.ki.ALT_PLUS,
            "ALT_MINUS": self.ki.ALT_MINUS,
            "ALT_LEFT": self.ki.ALT_LEFT,
            "ALT_UP": self.ki.ALT_UP,
            "ALT_DOWN": self.ki.ALT_DOWN,
            "ALT_RIGHT": self.ki.ALT_RIGHT,
            "ALT_0": self.ki.ALT_0,
            "LNG_LEFT": self.ki.LNG_LEFT,
            "LNG_UP": self.ki.LNG_UP,
            "LNG_DOWN": self.ki.LNG_DOWN,
            "LNG_RIGHT": self.ki.LNG_RIGHT,
            "LNG_SQUARE": self.ki.LNG_SQUARE,
        }

        self.network = sys_utils.Network()

        # Initialize Flask app with absolute template path
        views2_path = os.path.join(os.path.dirname(__file__), "..", "views2")
        views2_path = os.path.abspath(views2_path)
        logger.debug(f"Template folder path: {views2_path}")

        app = Flask(__name__, template_folder=views2_path)
        app.secret_key = SESSION_SECRET
        app.config["DEBUG"] = True
        logger.info(f"Flask app created successfully: {app}")
        logger.info(f"Template folder: {app.template_folder}")

        # Setup Babel for i18n
        Babel(app, locale_selector=server2_locale)  # Picked up by app variable

        # Configure Jinja2 environment for i18n
        app.jinja_env.add_extension("jinja2.ext.i18n")

        # Use PiFinder's global gettext function in templates
        import builtins

        app.jinja_env.globals["_"] = builtins._

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
        #     except:
        #         return text

        # # Make translation function available to routes
        # app.jinja_env.globals['_'] = translate

        # Static files routes
        @app.route("/images/<path:filename>")
        def send_image(filename):
            return send_file(f"../views2/images/{filename}", mimetype="image/png")

        @app.route("/js/<path:filename>")
        def send_js(filename):
            return send_file(f"../views2/js/{filename}")

        @app.route("/css/<path:filename>")
        def send_css(filename):
            return send_file(f"../views2/css/{filename}")

        @app.route("/")
        def home():
            logger.debug("/ called")
            # Get version info
            software_version = "Unknown"
            try:
                with open(self.version_txt, "r") as ver_f:
                    software_version = ver_f.read()
            except (FileNotFoundError, IOError) as e:
                logger.warning(f"Could not read version file: {str(e)}")

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
                    if solution:
                        hh, mm, _ = calc_utils.ra_to_hms(solution["RA"])
                        ra_text = f"{hh:02.0f}h{mm:02.0f}m"
                        dec_text = f"{solution['Dec']: .2f}"
            except Exception as e:
                logger.error(f"Failed to get solution data: {str(e)}")

            # Render the template with available data
            return app.jinja_env.get_template("index.html").render(
                title=gettext("Home"),
                software_version=software_version,
                wifi_mode=self.network.wifi_mode(),
                ip=self.network.local_ip(),
                network_name=self.network.get_connected_ssid(),
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
                origin_url = session.get("origin_url", "/")
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
                origin_url = session.get("origin_url", "/")
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
            gps_lock(float(lat), float(lon), float(altitude))
            if time_req and date_req:
                datetime_str = f"{date_req} {time_req}"
                datetime_obj = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
                datetime_utc = datetime_obj.replace(tzinfo=timezone.utc)
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
                name = request.form.get("name").strip()
                lat = float(request.form.get("latitude"))
                lon = float(request.form.get("longitude"))
                altitude = float(request.form.get("altitude"))
                error_in_m = float(request.form.get("error_in_m", "0"))
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

                name = request.form.get("name").strip()
                lat = float(request.form.get("latitude"))
                lon = float(request.form.get("longitude"))
                altitude = float(request.form.get("altitude"))
                error_in_m = float(request.form.get("error_in_m", "0"))
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
            return app.jinja_env.get_template("restart.html").render(title=_("Restart"))

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

        @app.route("/equipment/set_active_instrument/<int:instrument_id>")
        @auth_required
        def set_active_instrument(instrument_id: int):
            cfg = config.Config()
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
            if username:
                instruments = pds.dsl_instruments(username)
                for instrument in instruments:
                    if instrument["type"] == 0:
                        # Skip the naked eye
                        continue

                    make = instrument["instrument_make"]["name"]

                    obstruction_perc = instrument["obstruction_perc"]
                    if obstruction_perc is None:
                        obstruction_perc = 0
                    else:
                        obstruction_perc = float(obstruction_perc)

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
                        aperture_mm=int(instrument["diameter"]),
                        focal_length_mm=int(instrument["diameter"] * instrument["fd"]),
                        obstruction_perc=obstruction_perc,
                        mount_type=instrument["mount_type"]["name"].lower(),
                        flip_image=bool(instrument["flip_image"]),
                        flop_image=bool(instrument["flop_image"]),
                        reverse_arrow_a=False,
                        reverse_arrow_b=False,
                    )
                    try:
                        cfg.equipment.telescopes.index(new_instrument)
                    except ValueError:
                        cfg.equipment.telescopes.append(new_instrument)

                # Add the eyepieces from deepskylog
                eyepieces = pds.dsl_eyepieces(username)
                for eyepiece in eyepieces:
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
                        afov=int(eyepiece["apparentFOV"]),
                        field_stop=float(eyepiece["field_stop_mm"]),
                    )
                    try:
                        cfg.equipment.eyepieces.index(new_eyepiece)
                    except ValueError:
                        cfg.equipment.eyepieces.append(new_eyepiece)

                cfg.save_equipment()
                self.ui_queue.put("reload_config")
            return app.jinja_env.get_template("equipment.html").render(
                title=_("Equipment"),
                equipment=config.Config().equipment,
                success_message=_(
                    "Equipment Imported, restart your PiFinder to use this new data"
                ),
            )

        @app.route("/equipment/edit_eyepiece/<int:eyepiece_id>")
        @auth_required
        def edit_eyepiece(eyepiece_id: int):
            if eyepiece_id >= 0:
                eyepiece = config.Config().equipment.eyepieces[eyepiece_id]
            else:
                eyepiece = Eyepiece(
                    make="", name="", focal_length_mm=0, afov=0, field_stop=0
                )

            return app.jinja_env.get_template("edit_eyepiece.html").render(
                title=_("Edit Eyepiece"), eyepiece=eyepiece, eyepiece_id=eyepiece_id
            )

        @app.route("/equipment/add_eyepiece/<int:eyepiece_id>", methods=["POST"])
        @auth_required
        def equipment_add_eyepiece(eyepiece_id: int):
            cfg = config.Config()

            try:
                make = request.form.get("make") or ""
                name = request.form.get("name") or ""
                focal_length_str = request.form.get("focal_length_mm") or "0"
                afov_str = request.form.get("afov") or "0"
                field_stop_str = request.form.get("field_stop") or "0"

                eyepiece = Eyepiece(
                    make=make,
                    name=name,
                    focal_length_mm=float(focal_length_str),
                    afov=int(afov_str),
                    field_stop=float(field_stop_str),
                )

                if eyepiece_id >= 0:
                    cfg.equipment.eyepieces[eyepiece_id] = eyepiece
                else:
                    try:
                        index = cfg.equipment.telescopes.index(eyepiece)
                        cfg.equipment.eyepieces[index] = eyepiece
                    except ValueError:
                        cfg.equipment.eyepieces.append(eyepiece)

                cfg.save_equipment()
                self.ui_queue.put("reload_config")
            except Exception as e:
                logger.error(f"Error adding eyepiece: {e}")

            return app.jinja_env.get_template("equipment.html").render(
                title=_("Equipment"),
                equipment=config.Config().equipment,
                success_message=_("Eyepiece added, restart your PiFinder to use"),
            )

        @app.route("/equipment/delete_eyepiece/<int:eyepiece_id>")
        @auth_required
        def equipment_delete_eyepiece(eyepiece_id: int):
            cfg = config.Config()
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

        @app.route("/equipment/edit_instrument/<int:instrument_id>")
        @auth_required
        def edit_instrument(instrument_id: int):
            if instrument_id >= 0:
                telescope = config.Config().equipment.telescopes[instrument_id]
            else:
                telescope = Telescope(
                    make="",
                    name="",
                    aperture_mm=0,
                    focal_length_mm=0,
                    obstruction_perc=0,
                    mount_type="",
                    flip_image=False,
                    flop_image=False,
                    reverse_arrow_a=False,
                    reverse_arrow_b=False,
                )

            return app.jinja_env.get_template("edit_instrument.html").render(
                title=_("Edit Instrument"),
                telescope=telescope,
                instrument_id=instrument_id,
            )

        @app.route("/equipment/add_instrument/<int:instrument_id>", methods=["POST"])
        @auth_required
        def equipment_add_instrument(instrument_id: int):
            cfg = config.Config()

            try:
                make = request.form.get("make") or ""
                name = request.form.get("name") or ""
                aperture_str = request.form.get("aperture") or "0"
                focal_length_str = request.form.get("focal_length_mm") or "0"
                obstruction_str = request.form.get("obstruction_perc") or "0"
                mount_type = request.form.get("mount_type") or ""

                instrument = Telescope(
                    make=make,
                    name=name,
                    aperture_mm=int(aperture_str),
                    focal_length_mm=int(focal_length_str),
                    obstruction_perc=float(obstruction_str),
                    mount_type=mount_type,
                    flip_image=bool(request.form.get("flip")),
                    flop_image=bool(request.form.get("flop")),
                    reverse_arrow_a=bool(request.form.get("reverse_arrow_a")),
                    reverse_arrow_b=bool(request.form.get("reverse_arrow_b")),
                )
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
                logger.error(f"Error adding instrument: {e}")
            return app.jinja_env.get_template("equipment.html").render(
                title=_("Equipment"),
                equipment=config.Config().equipment,
                success_message=_("Instrument Added, restart your PiFinder to use"),
            )

        @app.route("/equipment/delete_instrument/<int:instrument_id>")
        @auth_required
        def equipment_delete_instrument(instrument_id: int):
            cfg = config.Config()
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
            # Get current log level
            root_logger = logging.getLogger()
            current_level = logging.getLevelName(root_logger.getEffectiveLevel())
            return app.jinja_env.get_template("logs.html").render(
                title=_("Logs"), current_level=current_level
            )

        @app.route("/logs/stream")
        @auth_required
        def stream_logs():
            try:
                position = int(request.args.get("position", 0))
                log_file = os.path.expanduser("~/PiFinder_data/pifinder.log")

                try:
                    file_size = os.path.getsize(log_file)
                    # If position is beyond file size or 0, start from beginning
                    if position >= file_size or position == 0:
                        position = 0

                    with open(log_file, "r") as f:
                        if position > 0:
                            f.seek(position)
                        new_lines = f.readlines()
                        new_position = f.tell()

                    # If we're at the start of the file, get all lines
                    # Otherwise, only return new lines if there are any
                    if position == 0 or new_lines:
                        return jsonify({"logs": new_lines, "position": new_position})
                    else:
                        return jsonify({"logs": [], "position": position})
                except FileNotFoundError:
                    logger.error(f"Log file not found: {log_file}")
                    return jsonify({"logs": [], "position": 0})

            except Exception as e:
                logger.error(f"Error streaming logs: {e}")
                return jsonify({"logs": [], "position": position})

        @app.route("/logs/current_level")
        @auth_required
        def get_current_log_level():
            root_logger = logging.getLogger()
            current_level = logging.getLevelName(root_logger.getEffectiveLevel())
            return jsonify({"level": current_level})

        @app.route("/logs/components")
        @auth_required
        def get_component_levels():
            try:
                import json5

                with open("pifinder_logconf.json", "r") as f:
                    config = json5.load(f)
                # Get all loggers from the config
                loggers = config.get("loggers", {})
                # Get current runtime levels for each logger
                current_levels = {}
                # Get all loggers from the config file
                for logger_name in loggers.keys():
                    logger = logging.getLogger(logger_name)
                    current_levels[logger_name] = {
                        "config_level": loggers.get(logger_name, {}).get(
                            "level", "INFO"
                        ),
                        "current_level": logging.getLevelName(
                            logger.getEffectiveLevel()
                        ),
                    }
                return jsonify({"components": current_levels})
            except Exception as e:
                logging.error(f"Error reading log configuration: {e}")
                return jsonify({"status": "error", "message": str(e)})

        @app.route("/logs/download")
        @auth_required
        def download_logs():
            import zipfile
            import tempfile
            from datetime import datetime

            try:
                # Create a temporary zip file
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

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
            if button in button_dict:
                self.key_callback(button_dict[button])
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

        def time_lock(time=datetime.now()):
            msg = ("time", time)
            self.gps_queue.put(msg)
            logger.debug("Putting time msg on gps_queue: {msg}")

        # Store the app reference for running
        self.app = app

    def run(self):
        # If the PiFinder software is running as a service
        # it can grab port 80.  If not, it needs to use 8080
        try:
            self.app.run(
                host="0.0.0.0",
                port=80,
                debug=True,
                use_reloader=False,
                passthrough_errors=False,
            )
            logger.info("Webserver started on port 80")
        except (PermissionError, OSError, SystemExit) as e:
            logger.debug(f"Permission denied on port 80, trying 8080. {e}")
            try:
                self.app.run(
                    host="0.0.0.0",
                    port=8080,
                    debug=True,
                    use_reloader=False,
                    passthrough_errors=False,
                )
                logger.info("Webserver started on port 8080")
            except (Exception, SystemExit) as e2:
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
    # MultiprocLogging.configurer(log_queue)
    logging.basicConfig(
        level=logging.DEBUG, format="%(asctime)s %(name)s:%(levelname)s:%(message)s"
    )
    server = Server2(keyboard_queue, ui_queue, gps_queue, shared_state, verbose)
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

    logger.info("Starting PiFinder Server2 in standalone mode")

    # Create a single queue for command line testing
    test_queue: multiprocessing.Queue = multiprocessing.Queue()

    # Create server with mock components
    server = Server2(
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
