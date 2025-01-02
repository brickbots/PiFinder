import time
from PiFinder.keyboard_interface import KeyboardInterface
import logging
from PiFinder.multiproclogging import MultiprocLogging

logger = logging.getLogger("Keyboard.Local")


class KeyboardLocal(KeyboardInterface):
    def __init__(self, q):
        try:
            from PyHotKey import Key, keyboard
        except ModuleNotFoundError:
            logger.error("pyhotkey not supported on pi hardware")
            return
        try:
            self.q = q
            keyboard.set_magickey_on_release(Key.left, self.callback, self.LEFT)
            keyboard.set_magickey_on_release(Key.up, self.callback, self.UP)
            keyboard.set_magickey_on_release(Key.down, self.callback, self.DOWN)
            keyboard.set_magickey_on_release(Key.right, self.callback, self.RIGHT)
            keyboard.set_magickey_on_release("q", self.callback, self.PLUS)
            keyboard.set_magickey_on_release("a", self.callback, self.MINUS)
            keyboard.set_magickey_on_release("z", self.callback, self.SQUARE)
            keyboard.set_magickey_on_release("m", self.callback, self.LNG_SQUARE)
            keyboard.set_magickey_on_release("0", self.callback, 0)
            keyboard.set_magickey_on_release("1", self.callback, 1)
            keyboard.set_magickey_on_release("2", self.callback, 2)
            keyboard.set_magickey_on_release("3", self.callback, 3)
            keyboard.set_magickey_on_release("4", self.callback, 4)
            keyboard.set_magickey_on_release("5", self.callback, 5)
            keyboard.set_magickey_on_release("6", self.callback, 6)
            keyboard.set_magickey_on_release("7", self.callback, 7)
            keyboard.set_magickey_on_release("8", self.callback, 8)
            keyboard.set_magickey_on_release("9", self.callback, 9)
            keyboard.set_magickey_on_release(
                [Key.ctrl, "q"], None, self.callback, self.ALT_PLUS
            )
            keyboard.set_magickey_on_release(
                [Key.ctrl, "a"], None, self.callback, self.ALT_MINUS
            )
            keyboard.set_magickey_on_release(
                [Key.ctrl, Key.left], None, self.callback, self.ALT_LEFT
            )
            keyboard.set_magickey_on_release(
                [Key.ctrl, Key.up], None, self.callback, self.ALT_UP
            )
            keyboard.set_magickey_on_release(
                [Key.ctrl, Key.down], None, self.callback, self.ALT_DOWN
            )
            keyboard.set_magickey_on_release(
                [Key.ctrl, Key.right], None, self.callback, self.ALT_RIGHT
            )
            keyboard.set_magickey_on_release(
                [Key.ctrl, "0"], None, self.callback, self.ALT_0
            )
            keyboard.set_magickey_on_release(
                [Key.shift, Key.left], None, self.callback, self.LNG_LEFT
            )
            keyboard.set_magickey_on_release(
                [Key.shift, Key.up], None, self.callback, self.LNG_RIGHT
            )
            keyboard.set_magickey_on_release(
                [Key.shift, Key.down], None, self.callback, self.LNG_DOWN
            )
            keyboard.set_magickey_on_release(
                [Key.shift, Key.right], None, self.callback, self.LNG_RIGHT
            )
            keyboard.set_magickey_on_release(
                [Key.shift, "z"], None, self.callback, self.LNG_SQUARE
            )
            keyboard.set_magickey_on_release("m", self.callback, self.LNG_SQUARE)
            keyboard.set_magickey_on_release("r", self.callback, self.LNG_RIGHT)
        except Exception as e:
            logger.error("KeyboardLocal.__init__: {}".format(e))
        # keyboard.logger = True
        logger.debug("KeyboardLocal.__init__")

    def callback(self, key):
        self.q.put(key)


def run_keyboard(q, shared_state, log_queue):
    MultiprocLogging.configurer(log_queue)
    KeyboardLocal(q)

    while True:
        # the KeyboardLocal class has callbacks to handle
        # keypresss.  We just need to not terminate here
        time.sleep(1)
