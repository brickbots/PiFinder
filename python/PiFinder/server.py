import time
import logging
import io
import datetime

from bottle import Bottle, run, request, template, response, static_file
from PIL import Image

from PiFinder.keyboard_interface import KeyboardInterface
from PiFinder import sys_utils


class Server:
    def __init__(self, q, gps_queue, shared_state):
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

        @app.route("/images/<filename:re:.*\.png>")
        def send_image(filename):
            return static_file(filename, root="views/images", mimetype="image/png")

        @app.route("/static/<filename>")
        def send_static(filename):
            return static_file(filename, root="views/static")

        @app.route("/")
        def home():
            # need to collect alittle status info here
            with open(os.path.join(root_dir, "version.txt"), "r") as ver_f:
                software_version = ver_f.read()

            net = sys_utils.network()
            return template(
                "index",
                software_version=software_version,
                wifi_mode=net.wifi_mode(),
                ip=net.local_ip(),
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

        logging.info("Starting web interface server")
        run(app, host="0.0.0.0", port=80, quiet=True, debug=True)

    def key_callback(self, key):
        self.q.put(key)


def run_server(q, gps_q, shared_state):
    Server(q, gps_q, shared_state)
