import logging
import io
import uuid
import json
from datetime import datetime, timezone
import time
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

from PIL import Image

from PiFinder.keyboard_interface import KeyboardInterface

try:
    from PiFinder import sys_utils
except ImportError:
    from PiFinder import sys_utils_fake as sys_utils  # type: ignore[no-redef]
from PiFinder import utils, calc_utils
from PiFinder.db.observations_db import (
    ObservationsDatabase,
)

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
    def __init__(self, q, gps_queue, shared_state, is_debug=False):
        self.version_txt = f"{utils.pifinder_dir}/version.txt"
        self.q = q
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
            # need to collect alittle status info here
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
                # set auth cookie, doesnt matter whats in it, just as long
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
            logger.debug("/gps: %f, %f, %f ", self.lat, self.lon, self.altitude)

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
        self.q.put(key)

    def update_gps(self):
        location = self.shared_state.location()
        if location["gps_lock"] is True:
            self.gps_locked = True
            self.lat = location["lat"]
            self.lon = location["lon"]
            self.altitude = location["altitude"]
        else:
            self.gps_locked = False
            self.lat = None
            self.lon = None
            self.altitude = None


def run_server(q, gps_q, shared_state, log_queue, verbose=False):
    MultiprocLogging.configurer(log_queue)
    Server(q, gps_q, shared_state, verbose)
