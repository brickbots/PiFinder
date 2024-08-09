import time
from PiFinder.keyboard_interface import KeyboardInterface
import logging

from PiFinder.multiproclogging import MultiprocLogging

logger = logging.getLogger("Keyboard.Local")


class KeyboardLocal(KeyboardInterface):
    def __init__(self, q):
        try:
            from PyHotKey import Key, keyboard_manager as manager
        except ModuleNotFoundError:
            logger.error("pyhotkey not supported on pi hardware")
            return
        try:
            self.q = q
            manager.set_wetkey_on_release(Key.left, self.callback, self.LEFT)
            manager.set_wetkey_on_release(Key.up, self.callback, self.UP)
            manager.set_wetkey_on_release(Key.down, self.callback, self.DOWN)
            manager.set_wetkey_on_release(Key.right, self.callback, self.RIGHT)
            manager.set_wetkey_on_release("q", self.callback, self.PLUS)
            manager.set_wetkey_on_release("a", self.callback, self.MINUS)
            manager.set_wetkey_on_release("z", self.callback, self.SQUARE)
            manager.set_wetkey_on_release("0", self.callback, 0)
            manager.set_wetkey_on_release("1", self.callback, 1)
            manager.set_wetkey_on_release("2", self.callback, 2)
            manager.set_wetkey_on_release("3", self.callback, 3)
            manager.set_wetkey_on_release("4", self.callback, 4)
            manager.set_wetkey_on_release("5", self.callback, 5)
            manager.set_wetkey_on_release("6", self.callback, 6)
            manager.set_wetkey_on_release("7", self.callback, 7)
            manager.set_wetkey_on_release("8", self.callback, 8)
            manager.set_wetkey_on_release("9", self.callback, 9)
            manager.register_hotkey([Key.ctrl, "q"], None, self.callback, self.ALT_PLUS)
            manager.register_hotkey(
                [Key.ctrl, "a"], None, self.callback, self.ALT_MINUS
            )
            manager.register_hotkey(
                [Key.ctrl, Key.left], None, self.callback, self.ALT_LEFT
            )
            manager.register_hotkey(
                [Key.ctrl, Key.up], None, self.callback, self.ALT_UP
            )
            manager.register_hotkey(
                [Key.ctrl, Key.down], None, self.callback, self.ALT_DOWN
            )
            manager.register_hotkey(
                [Key.ctrl, Key.right], None, self.callback, self.ALT_RIGHT
            )
            manager.register_hotkey([Key.ctrl, "0"], None, self.callback, self.ALT_0)
            manager.register_hotkey(
                [Key.shift, Key.left], None, self.callback, self.LNG_LEFT
            )
            manager.register_hotkey(
                [Key.shift, Key.up], None, self.callback, self.LNG_RIGHT
            )
            manager.register_hotkey(
                [Key.shift, Key.down], None, self.callback, self.LNG_DOWN
            )
            manager.register_hotkey(
                [Key.shift, Key.right], None, self.callback, self.LNG_RIGHT
            )
            manager.register_hotkey(
                [Key.shift, "z"], None, self.callback, self.LNG_SQUARE
            )
        except Exception as e:
            logger.error("KeyboardLocal.__init__: {}".format(e))
        # manager.logger = True
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
