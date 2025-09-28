import time
from PiFinder.keyboard_interface import KeyboardInterface
import logging
from PiFinder.multiproclogging import MultiprocLogging

logger = logging.getLogger("Keyboard.Local")


class KeyboardLocal(KeyboardInterface):
    """'
    Keyboard used with `python -m PiFinder.main -k local`

    PyHotKey does not support key combinations, so we map single keys to combination of button presses here.

    In addition to the arrow keys (LEFT, UP, DOWN, RIGHT), the following keys are mapped on an english keyboard layout:
    (Note that in other locales, the position of the keys may differ, but the meaning is the same)

       0   1   2   3   4   5   6   7   8   9     <-- number keys
        q   w   e   r   .   .   .   i   .   .
         a   s   d   f   g   .   j   k   l
          z   .   .   .   .   .   m   .   .   .
         ^   ^    ^^^^^^^^        ^ ^^^^^^- j=LNG_LEFT, i=LNG_UP, k=LNG_DOWN, l=LNG_RIGHT
         |   |    |               + m = LNG_SQUARE
         |   |    + e = ALT+0; d=ALT+LEFT, r=ALT+UP, f=ALT+DOWN, g=ALT+RIGHT
         |   + w=ALT+PLUS, s=ALT+MINUS
         + q=PLUS, a=MINUS, z=SQUARE

    Note: ALT_<key> means that SQUARE+<key> is pressed.
    """

    def __init__(self, q):
        try:
            from PyHotKey import Key, keyboard
        except ModuleNotFoundError:
            logger.error("pyhotkey not supported on pi hardware")
            return
        try:
            self.q = q
            # Configure unmodified keys
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
            # ALT_* single key mappings

            # On english keyboard, w and s are next to q and a (see above)
            keyboard.set_magickey_on_release("w", self.callback, self.ALT_PLUS)
            keyboard.set_magickey_on_release("s", self.callback, self.ALT_MINUS)

            # On english keyboard: ALT mappings
            #  e  r
            #   d  f  g
            keyboard.set_magickey_on_release("d", self.callback, self.ALT_LEFT)
            keyboard.set_magickey_on_release("r", self.callback, self.ALT_UP)
            keyboard.set_magickey_on_release("f", self.callback, self.ALT_DOWN)
            keyboard.set_magickey_on_release("g", self.callback, self.ALT_RIGHT)
            keyboard.set_magickey_on_release("e", self.callback, self.ALT_0)

            # LNG_* single key mappings

            # On english keyboard:
            #    i
            #  j  k  l
            keyboard.set_magickey_on_release("j", self.callback, self.LNG_LEFT)
            keyboard.set_magickey_on_release("i", self.callback, self.LNG_UP)
            keyboard.set_magickey_on_release("k", self.callback, self.LNG_DOWN)
            keyboard.set_magickey_on_release("l", self.callback, self.LNG_RIGHT)
        except Exception as e:
            logger.error("KeyboardLocal.__init__: {}".format(e))
        # keyboard.logger = True
        logger.debug("KeyboardLocal.__init__")

    def callback(self, key):
        self.q.put(key)


def run_keyboard(q, shared_state, log_queue, bloom_remap=False):
    MultiprocLogging.configurer(log_queue)
    KeyboardLocal(q)

    while True:
        # the KeyboardLocal class has callbacks to handle
        # keypresses.  We just need to not terminate here
        time.sleep(1)
