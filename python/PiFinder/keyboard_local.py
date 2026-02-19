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

            logger.info("PyHotKey imported successfully")
        except ModuleNotFoundError:
            logger.error("pyhotkey not supported on pi hardware")
            return
        except Exception as e:
            logger.error(f"Failed to import PyHotKey: {e}", exc_info=True)
            return
        try:
            logger.info("Setting up keyboard bindings...")
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
            logger.info("Keyboard bindings set up successfully")
        except Exception as e:
            logger.error("KeyboardLocal.__init__ failed: {}".format(e), exc_info=True)
        # keyboard.logger = True
        logger.info("KeyboardLocal.__init__ complete")

    def callback(self, key):
        self.q.put(key)


def run_keyboard(q, shared_state, log_queue, bloom_remap=False):
    MultiprocLogging.configurer(log_queue)

    logger.info("Keyboard process starting...")

    # Try pynput directly first (more reliable on macOS)
    try:
        from pynput import keyboard as pynput_keyboard

        logger.info("Using pynput for keyboard handling")

        # Key mapping
        key_map = {
            pynput_keyboard.Key.left: KeyboardInterface.LEFT,
            pynput_keyboard.Key.up: KeyboardInterface.UP,
            pynput_keyboard.Key.down: KeyboardInterface.DOWN,
            pynput_keyboard.Key.right: KeyboardInterface.RIGHT,
            "q": KeyboardInterface.PLUS,
            "a": KeyboardInterface.MINUS,
            "z": KeyboardInterface.SQUARE,
            "m": KeyboardInterface.LNG_SQUARE,
            "0": 0,
            "1": 1,
            "2": 2,
            "3": 3,
            "4": 4,
            "5": 5,
            "6": 6,
            "7": 7,
            "8": 8,
            "9": 9,
            "w": KeyboardInterface.ALT_PLUS,
            "s": KeyboardInterface.ALT_MINUS,
            "d": KeyboardInterface.ALT_LEFT,
            "r": KeyboardInterface.ALT_UP,
            "f": KeyboardInterface.ALT_DOWN,
            "g": KeyboardInterface.ALT_RIGHT,
            "e": KeyboardInterface.ALT_0,
            "j": KeyboardInterface.LNG_LEFT,
            "i": KeyboardInterface.LNG_UP,
            "k": KeyboardInterface.LNG_DOWN,
            "l": KeyboardInterface.LNG_RIGHT,
        }

        def on_release(key):
            try:
                # Handle special keys
                if key in key_map:
                    q.put(key_map[key])
                    logger.debug(f"Key released: {key} -> {key_map[key]}")
                # Handle character keys
                elif hasattr(key, "char") and key.char in key_map:
                    q.put(key_map[key.char])
                    logger.debug(f"Key released: {key.char} -> {key_map[key.char]}")
            except Exception as e:
                logger.error(f"Error handling key: {e}")

        # Start listener
        listener = pynput_keyboard.Listener(on_release=on_release)
        listener.start()
        logger.info("pynput keyboard listener started")

        while True:
            time.sleep(1)

    except Exception as e:
        logger.error(f"pynput failed, falling back to PyHotKey: {e}", exc_info=True)

        # Fallback to PyHotKey
        try:
            KeyboardLocal(q)
            logger.info("KeyboardLocal initialized successfully")
        except Exception as e2:
            logger.error(f"Failed to initialize KeyboardLocal: {e2}", exc_info=True)
            return

        while True:
            time.sleep(1)
