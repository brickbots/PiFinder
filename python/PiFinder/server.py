import io
import json
import logging
import time
import uuid
from datetime import datetime, timezone

import pydeepskylog as pds
from PIL import Image
from PiFinder import utils, calc_utils, config
from PiFinder.db.observations_db import (
    ObservationsDatabase,
)
from PiFinder.equipment import Telescope, Eyepiece
from PiFinder.keyboard_interface import KeyboardInterface
from PiFinder.multiproclogging import MultiprocLogging
from bottle import (
    Bottle,
    run,
    request,
    template,
    response,
    static_file,
    debug,
    redirect,
    CherootServer,
)

sys_utils = utils.get_sys_utils()

logger = logging.getLogger("Server")

# Generate a secret to validate the auth cookie
SESSION_SECRET = str(uuid.uuid4())


def auth_required(func):
    def auth_wrapper(*args, **kwargs):
        # check for and validate cookie
        auth_cookie = request.get_cookie("pf_auth", secret=SESSION_SECRET)
        if auth_cookie:
            return func(*args, **kwargs)

        return template("login", origin_url=request.url)

    return auth_wrapper


class Server:
    def __init__(
        self, keyboard_queue, ui_queue, gps_queue, shared_state, is_debug=False
    ):
        self.version_txt = f"{utils.pifinder_dir}/version.txt"
        self.keyboard_queue = keyboard_queue
        self.ui_queue = ui_queue
        self.gps_queue = gps_queue
        self.shared_state = shared_state
        self.ki = KeyboardInterface()
        # gps info
        self.lat = None
        self.lon = None
        self.altitude = None
        self.gps_locked = False

        if is_debug:
            logger.setLevel(logging.DEBUG)

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

        app = Bottle()
        debug(True)

        @app.route(r"/images/<filename:re:.*\.png>")
        def send_image(filename):
            return static_file(filename, root="views/images", mimetype="image/png")

        @app.route("/js/<filename>")
        def send_js(filename):
            return static_file(filename, root="views/js")

        @app.route("/css/<filename>")
        def send_css(filename):
            return static_file(filename, root="views/css")

        @app.route("/")
        def home():
            logger.debug("/ called")
            # need to collect a little status info here
            with open(self.version_txt, "r") as ver_f:
                software_version = ver_f.read()

            self.update_gps()
            lat_text = ""
            lon_text = ""
            gps_icon = "gps_off"
            gps_text = "Not Locked"
            if self.gps_locked is True:
                gps_icon = "gps_fixed"
                gps_text = "Locked"
                lat_text = str(self.lat)
                lon_text = str(self.lon)

            ra_text = "0"
            dec_text = "0"
            camera_icon = "broken_image"
            if self.shared_state.solve_state() is True:
                camera_icon = "camera_alt"
                solution = self.shared_state.solution()
                hh, mm, _ = calc_utils.ra_to_hms(solution["RA"])
                ra_text = f"{hh:02.0f}h{mm:02.0f}m"
                dec_text = f"{solution['Dec']: .2f}"

            return template(
                "index",
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

        @app.route("/login", method="post")
        def login():
            password = request.forms.get("password")
            origin_url = request.forms.get("origin_url", "/")
            if sys_utils.verify_password("pifinder", password):
                # set auth cookie, doesn't matter what's in it, just as long
                # as it's there and cryptographically valid
                response.set_cookie("pf_auth", str(uuid.uuid4()), secret=SESSION_SECRET)
                redirect(origin_url)
            else:
                return template(
                    "login", origin_url=origin_url, error_message="Invalid Password"
                )

        @app.route("/remote")
        @auth_required
        def remote():
            return template(
                "remote",
            )

        @app.route("/advanced")
        @auth_required
        def advanced():
            return template(
                "advanced",
            )

        @app.route("/network")
        @auth_required
        def network_page():
            show_new_form = request.query.add_new or 0

            return template(
                "network",
                net=self.network,
                show_new_form=show_new_form,
            )

        @app.route("/gps")
        @auth_required
        def gps_page():
            self.update_gps()
            show_new_form = request.query.add_new or 0
            logger.debug(
                "/gps: %f, %f, %f ",
                self.lat or 0.0,
                self.lon or 0.0,
                self.altitude or 0.0,
            )

            return template(
                "gps",
                show_new_form=show_new_form,
                lat=self.lat,
                lon=self.lon,
                altitude=self.altitude,
            )

        @app.route("/gps/update", method="post")
        @auth_required
        def gps_update():
            lat = request.forms.get("latitudeDecimal")
            lon = request.forms.get("longitudeDecimal")
            altitude = request.forms.get("altitude")
            date_req = request.forms.get("date")
            time_req = request.forms.get("time")
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
            return home()

        @app.route("/network/add", method="post")
        @auth_required
        def network_add():
            ssid = request.forms.get("ssid")
            psk = request.forms.get("psk")
            if len(psk) < 8:
                key_mgmt = "NONE"
            else:
                key_mgmt = "WPA-PSK"

            self.network.add_wifi_network(ssid, key_mgmt, psk)
            return network_page()

        @app.route("/network/delete/<network_id:int>")
        @auth_required
        def network_delete(network_id):
            self.network.delete_wifi_network(network_id)
            return network_page()

        @app.route("/network/update", method="post")
        @auth_required
        def network_update():
            wifi_mode = request.forms.get("wifi_mode")
            ap_name = request.forms.get("ap_name")
            host_name = request.forms.get("host_name")

            self.network.set_wifi_mode(wifi_mode)
            self.network.set_ap_name(ap_name)
            self.network.set_host_name(host_name)
            return template("restart")

        @app.route("/tools/pwchange", method="post")
        @auth_required
        def password_change():
            current_password = request.forms.get("current_password")
            new_passworda = request.forms.get("new_passworda")
            new_passwordb = request.forms.get("new_passwordb")

            if new_passworda == "" or current_password == "" or new_passwordb == "":
                return template(
                    "tools", error_message="You must fill in all password fields"
                )

            if new_passworda == new_passwordb:
                if sys_utils.change_password(
                    "pifinder", current_password, new_passworda
                ):
                    return template("tools", status_message="Password Changed")
                else:
                    return template("tools", error_message="Incorrect current password")
            else:
                return template("tools", error_message="New passwords do not match")

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
            return template("equipment", equipment=config.Config().equipment)

        @app.route("/equipment/set_active_instrument/<instrument_id:int>")
        @auth_required
        def set_active_instrument(instrument_id: int):
            cfg = config.Config()
            cfg.equipment.set_active_telescope(cfg.equipment.telescopes[instrument_id])
            cfg.save_equipment()
            self.ui_queue.put("reload_config")
            return template(
                "equipment",
                equipment=cfg.equipment,
                success_message=cfg.equipment.active_telescope.make
                + " "
                + cfg.equipment.active_telescope.name
                + " set as active instrument.",
            )

        @app.route("/equipment/set_active_eyepiece/<eyepiece_id:int>")
        @auth_required
        def set_active_eyepiece(eyepiece_id: int):
            cfg = config.Config()
            cfg.equipment.set_active_eyepiece(cfg.equipment.eyepieces[eyepiece_id])
            cfg.save_equipment()
            self.ui_queue.put("reload_config")
            return template(
                "equipment",
                equipment=cfg.equipment,
                success_message=cfg.equipment.active_eyepiece.make
                + " "
                + cfg.equipment.active_eyepiece.name
                + " set as active eyepiece.",
            )

        @app.route("/equipment/import_from_deepskylog", method="post")
        @auth_required
        def equipment_import():
            username = request.forms.get("dsl_name")
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

                    new_eyepiece = Eyepiece(
                        make="",
                        name=eyepiece["name"],
                        focal_length_mm=float(eyepiece["focalLength"]),
                        afov=int(eyepiece["apparentFOV"]),
                        field_stop=0.0,
                    )
                    try:
                        cfg.equipment.eyepieces.index(new_eyepiece)
                    except ValueError:
                        cfg.equipment.eyepieces.append(new_eyepiece)

                cfg.save_equipment()
                self.ui_queue.put("reload_config")
            return template(
                "equipment",
                equipment=config.Config().equipment,
                success_message="Equipment Imported, restart your PiFinder to use this new data",
            )

        @app.route("/equipment/edit_eyepiece/<eyepiece_id:int>")
        @auth_required
        def edit_eyepiece(eyepiece_id: int):
            if eyepiece_id >= 0:
                eyepiece = config.Config().equipment.eyepieces[eyepiece_id]
            else:
                eyepiece = Eyepiece(
                    make="", name="", focal_length_mm=0, afov=0, field_stop=0
                )

            return template("edit_eyepiece", eyepiece=eyepiece, eyepiece_id=eyepiece_id)

        @app.route("/equipment/add_eyepiece/<eyepiece_id:int>", method="post")
        @auth_required
        def equipment_add_eyepiece(eyepiece_id: int):
            cfg = config.Config()

            try:
                eyepiece = Eyepiece(
                    make=request.forms.get("make"),
                    name=request.forms.get("name"),
                    focal_length_mm=float(request.forms.get("focal_length_mm")),
                    afov=int(request.forms.get("afov")),
                    field_stop=float(request.forms.get("field_stop")),
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

            return template(
                "equipment",
                equipment=config.Config().equipment,
                success_message="Eyepiece added, restart your PiFinder to use",
            )

        @app.route("/equipment/delete_eyepiece/<eyepiece_id:int>")
        @auth_required
        def equipment_delete_eyepiece(eyepiece_id: int):
            cfg = config.Config()
            cfg.equipment.eyepieces.pop(eyepiece_id)
            cfg.save_equipment()
            self.ui_queue.put("reload_config")
            return template(
                "equipment",
                equipment=config.Config().equipment,
                success_message="Eyepiece Deleted, restart your PiFinder to remove from menu",
            )

        @app.route("/equipment/edit_instrument/<instrument_id:int>")
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

            return template(
                "edit_instrument", telescope=telescope, instrument_id=instrument_id
            )

        @app.route("/equipment/add_instrument/<instrument_id:int>", method="post")
        @auth_required
        def equipment_add_instrument(instrument_id: int):
            cfg = config.Config()

            try:
                instrument = Telescope(
                    make=request.forms.get("make"),
                    name=request.forms.get("name"),
                    aperture_mm=int(request.forms.get("aperture")),
                    focal_length_mm=int(request.forms.get("focal_length_mm")),
                    obstruction_perc=float(request.forms.get("obstruction_perc")),
                    mount_type=request.forms.get("mount_type"),
                    flip_image=bool(request.forms.get("flip")),
                    flop_image=bool(request.forms.get("flop")),
                    reverse_arrow_a=bool(request.forms.get("reverse_arrow_a")),
                    reverse_arrow_b=bool(request.forms.get("reverse_arrow_b")),
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
            return template(
                "equipment",
                equipment=config.Config().equipment,
                success_message="Instrument Added, restart your PiFinder to use",
            )

        @app.route("/equipment/delete_instrument/<instrument_id:int>")
        @auth_required
        def equipment_delete_instrument(instrument_id: int):
            cfg = config.Config()
            cfg.equipment.telescopes.pop(instrument_id)
            cfg.save_equipment()
            self.ui_queue.put("reload_config")
            return template(
                "equipment",
                equipment=config.Config().equipment,
                success_message="Instrument Deleted, restart your PiFinder to remove from menu",
            )

        @app.route("/observations")
        @auth_required
        def obs_sessions():
            obs_db = ObservationsDatabase()
            if request.query.get("download", 0) == "1":
                # Download all as TSV
                observations = obs_db.observations_as_tsv()

                response.set_header(
                    "Content-Disposition", "attachment; filename=observations.tsv"
                )
                response.set_header("Content-Type", "text/tsv")
                return observations

            # regular html page of sessions
            sessions = obs_db.get_sessions()
            metadata = {
                "sess_count": len(sessions),
                "object_count": sum(x["observations"] for x in sessions),
                "total_duration": sum(x["duration"] for x in sessions),
            }
            return template("obs_sessions", sessions=sessions, metadata=metadata)

        @app.route("/observations/<session_id>")
        @auth_required
        def obs_session(session_id):
            obs_db = ObservationsDatabase()
            if request.query.get("download", 0) == "1":
                # Download all as TSV
                observations = obs_db.observations_as_tsv(session_id)

                response.set_header(
                    "Content-Disposition",
                    f"attachment; filename=observations_{session_id}.tsv",
                )
                response.set_header("Content-Type", "text/tsv")
                return observations

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
            return template("obs_session_log", session=session, objects=ret_objects)

        @app.route("/tools")
        @auth_required
        def tools():
            return template("tools")

        @app.route("/tools/backup")
        @auth_required
        def tools_backup():
            _backup_file = sys_utils.backup_userdata()

            # Assumes the standard backup location
            return static_file("PiFinder_backup.zip", "/home/pifinder/PiFinder_data")

        @app.route("/tools/restore", method="post")
        @auth_required
        def tools_restore():
            sys_utils.remove_backup()
            backup_file = request.files.get("backup_file")
            backup_file.filename = "PiFinder_backup.zip"
            backup_file.save("/home/pifinder/PiFinder_data")

            sys_utils.restore_userdata(
                "/home/pifinder/PiFinder_data/PiFinder_backup.zip"
            )

            return template("restart_pifinder")

        @app.route("/key_callback", method="POST")
        @auth_required
        def key_callback():
            button = request.json.get("button")
            if button in button_dict:
                self.key_callback(button_dict[button])
            else:
                self.key_callback(int(button))
            return {"message": "success"}

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
            response.content_type = "image/png"  # adjust for your image format

            if img is None:
                img = empty_img
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format="PNG")  # adjust for your image format
            img_byte_arr = img_byte_arr.getvalue()

            return img_byte_arr

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

        @auth_required
        def time_lock(time=datetime.now()):
            msg = ("time", time)
            self.gps_queue.put(msg)
            logger.debug("Putting time msg on gps_queue: {msg}")

        # If the PiFinder software is running as a service
        # it can grab port 80.  If not, it needs to use 8080
        try:
            run(
                app,
                host="0.0.0.0",
                port=80,
                quiet=True,
                debug=True,
                server=CherootServer,
            )
        except (PermissionError, OSError):
            logger.info("Web Interface on port 8080")
            run(
                app,
                host="0.0.0.0",
                port=8080,
                quiet=True,
                debug=True,
                server=CherootServer,
            )

    def key_callback(self, key):
        self.keyboard_queue.put(key)

    def update_gps(self):
        location = self.shared_state.location()
        logging.debug(
            "self shared state is %s and location is %s", self.shared_state, location
        )
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
    Server(keyboard_queue, ui_queue, gps_queue, shared_state, verbose)
