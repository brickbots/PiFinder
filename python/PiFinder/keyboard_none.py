import time
from PiFinder.keyboard_interface import KeyboardInterface
import logging

logger = logging.getLogger("KeyboardNone")

class KeyboardNone(KeyboardInterface):
    def __init__(self, q):
        try:
            self.q = q
        except Exception as e:
            logger.error("KeyboardLocal.__init__: {}".format(e))
        # manager.logger = True
        logger.debug("KeyboardLocal.__init__")

    def callback(self, key):
        self.q.put(key)


def run_keyboard(q, shared_state):
    KeyboardNone(q)

    while True:
        # the KeyboardLocal class has callbacks to handle
        # keypresss.  We just need to not terminate here
        time.sleep(1)
