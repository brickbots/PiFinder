import time
import logging
import io
import datetime

from bottle import Bottle, run, request, template, response, static_file, debug
from PIL import Image

from PiFinder.keyboard_interface import KeyboardInterface
from PiFinder import sys_utils, utils, calc_utils


class Server:
    def __init__(self, q, gps_queue, shared_state):
        self.version_txt = f"{utils.pifinder_dir}/version.txt"
        self.q = q
        self.gps_queue = gps_queue
        self.shared_state = shared_state
        self.ki = KeyboardInterface()

        button_dict = {
            "UP": self.ki.UP,
            "DN": self.ki.DN,
            "ENT": self.ki.ENT,
            "A": self.ki.A,
            "B": self.ki.B,
            "C": self.ki.C,
            "D": self.ki.D,
            "ALT_UP": self.ki.ALT_UP,
            "ALT_DN": self.ki.ALT_DN,
            "ALT_A": self.ki.ALT_A,
            "ALT_B": self.ki.ALT_B,
            "ALT_C": self.ki.ALT_C,
            "ALT_D": self.ki.ALT_D,
            "ALT_0": self.ki.ALT_0,
            "LNG_A": self.ki.LNG_A,
            "LNG_B": self.ki.LNG_B,
            "LNG_C": self.ki.LNG_C,
            "LNG_D": self.ki.LNG_D,
            "LNG_ENT": self.ki.LNG_ENT,
        }

        app = Bottle()
        debug(True)

        @app.route("/images/<filename:re:.*\.png>")
        def send_image(filename):
            return static_file(filename, root="views/images", mimetype="image/png")

        @app.route("/js/<filename>")
        def send_static(filename):
            return static_file(filename, root="views/js")

        @app.route("/css/<filename>")
        def send_static(filename):
            return static_file(filename, root="views/css")

        @app.route("/")
        def home():
            # need to collect alittle status info here
            with open(self.version_txt, "r") as ver_f:
                software_version = ver_f.read()

            location = self.shared_state.location()

            lat_text = ""
            lon_text = ""
            gps_icon = "gps_off"
            gps_text = "Not Locked"
            if location["gps_lock"] == True:
                gps_icon = "gps_fixed"
                gps_text = "Locked"
                lat_text = str(location["lat"])
                lon_text = str(location["lon"])

            ra_text = "0"
            dec_text = "0"
            camera_icon = "broken_image"
            if self.shared_state.solve_state() == True:
                camera_icon = "camera_alt"
                solution = self.shared_state.solution()
                hh, mm, _ = calc_utils.ra_to_hms(solution["RA"])
                ra_text = f"{hh:02.0f}h{mm:02.0f}m"
                dec_text = f"{solution['Dec']: .2f}"

            net = sys_utils.network()
            return template(
                "index",
                software_version=software_version,
                wifi_mode=net.wifi_mode(),
                ip=net.local_ip(),
                gps_icon=gps_icon,
                gps_text=gps_text,
                lat_text=lat_text,
                lon_text=lon_text,
                camera_icon=camera_icon,
                ra_text=ra_text,
                dec_text=dec_text,
            )

        @app.route("/remote")
        def remote():
            return template(
                "remote",
            )

        @app.route("/key_callback", method="POST")
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

        @app.route("/gps-lock")
        def gps_lock():
            msg = (
                "fix",
                {
                    "lat": 50,
                    "lon": 3,
                    "altitude": 10,
                },
            )
            self.gps_queue.put(msg)

        @app.route("/time-lock")
        def time_lock():
            msg = ("time", datetime.datetime.now())
            self.gps_queue.put(msg)

        # If the PiFinder software is running as a service
        # it can grab port 80.  If not, it needs to use 8080
        try:
            run(app, host="0.0.0.0", port=80, quiet=True, debug=True)
        except PermissionError:
            logging.info("Web Interface on port 8080")
            run(app, host="0.0.0.0", port=8080, quiet=True, debug=True)

    def key_callback(self, key):
        self.q.put(key)


def run_server(q, gps_q, shared_state):
    Server(q, gps_q, shared_state)
