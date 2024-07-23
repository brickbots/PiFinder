import time
from PiFinder.keyboard_interface import KeyboardInterface
import logging


class KeyboardNone(KeyboardInterface):
    def __init__(self, q):
        self.log = logging.getLogger("KeyboardLocal")
        try:
            self.q = q
        except Exception as e:
            logging.error("KeyboardLocal.__init__: {}".format(e))
        # manager.logger = True
        logging.debug("KeyboardLocal.__init__")

    def callback(self, key):
        self.q.put(key)


def run_keyboard(q, shared_state):
    KeyboardNone(q)

    while True:
        # the KeyboardLocal class has callbacks to handle
        # keypresss.  We just need to not terminate here
        time.sleep(1)
