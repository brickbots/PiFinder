import time
from PiFinder.keyboard_interface import KeyboardInterface
import logging
from PIL import Image
import io


class KeyboardServer(KeyboardInterface):
    def __init__(self, q, shared_state):
        from bottle import Bottle, run, request, template, response

        self.q = q
        self.shared_state = shared_state

        button_dict = {
            "UP": self.UP,
            "DN": self.DN,
            "ENT": self.ENT,
            "A": self.A,
            "B": self.B,
            "C": self.C,
            "D": self.D,
            "ALT_UP": self.ALT_UP,
            "ALT_DN": self.ALT_DN,
            "ALT_A": self.ALT_A,
            "ALT_B": self.ALT_B,
            "ALT_C": self.ALT_C,
            "ALT_D": self.ALT_D,
            "ALT_0": self.ALT_0,
            "LNG_A": self.LNG_A,
            "LNG_B": self.LNG_B,
            "LNG_C": self.LNG_C,
            "LNG_D": self.LNG_D,
            "LNG_ENT": self.LNG_ENT,
        }

        app = Bottle()

        @app.route("/")
        def home():
            return template("index")

        @app.route("/callback", method="POST")
        def callback():
            button = request.json.get("button")
            if button in button_dict:
                self.callback(button_dict[button])
            else:
                self.callback(int(button))
            return {"message": "success"}

        @app.route("/image")
        def serve_pil_image():
            img = Image.new(
                "RGB", (60, 30), color=(73, 109, 137)
            )  # create an image using PIL
            try:
                img = self.shared_state.screen()
            except (BrokenPipeError, EOFError):
                pass
            response.content_type = "image/png"  # adjust for your image format

            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format="PNG")  # adjust for your image format
            img_byte_arr = img_byte_arr.getvalue()

            return img_byte_arr

        logging.info("Starting keyboard server on port 8080")
        run(app, host="0.0.0.0", port=8080, quiet=True)

    def callback(self, key):
        self.q.put(key)


def run_keyboard(q, shared_state):
    KeyboardServer(q, shared_state)
