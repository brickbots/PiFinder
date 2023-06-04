import time
from PiFinder.keyboard_interface import KeyboardInterface
import logging

class KeyboardServer(KeyboardInterface):

    def __init__(self, q):
        from bottle import Bottle, run, request, template
        self.q = q 
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
            "LNG_ENT": self.LNG_ENT
        }
 
        app = Bottle()

        @app.route('/')
        def home():
            return template('index')

        @app.route('/callback', method='POST')
        def callback():
            button = request.json.get('button')
            if button in button_dict:
                self.callback(button_dict[button])
            else:
                self.callback(int(button))
            return {"message": "success"}

        run(app, host='0.0.0.0', port=8080)


    def callback(self, key):
        self.q.put(key)


def run_keyboard(q, script_path=None):
    keyboard = KeyboardServer(q)
