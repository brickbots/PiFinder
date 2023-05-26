from PiFinder.keyboard_interface import KeyboardInterface
from PyHotKey import Key, keyboard_manager as manager


class KeyboardLocal(KeyboardInterface):

    def __init__(self, q):
        self.q = q
        manager.set_wetkey_on_release(Key.enter, self.callback, self.B)
        manager.set_wetkey_on_release(Key.up, self.callback, self.B)
        manager.set_wetkey_on_release(Key.down, self.callback, self.B)
        manager.set_wetkey_on_release('a', self.callback, self.A)
        manager.set_wetkey_on_release('b', self.callback, self.B)
        manager.set_wetkey_on_release('c', self.callback, self.C)
        manager.set_wetkey_on_release('d', self.callback, self.D)
        manager.set_wetkey_on_release('0', self.callback, 0)
        manager.set_wetkey_on_release('1', self.callback, 1)
        manager.set_wetkey_on_release('2', self.callback, 2)
        manager.set_wetkey_on_release('3', self.callback, 3)
        manager.set_wetkey_on_release('4', self.callback, 4)
        manager.set_wetkey_on_release('5', self.callback, 5)
        manager.set_wetkey_on_release('6', self.callback, 6)
        manager.set_wetkey_on_release('7', self.callback, 7)
        manager.set_wetkey_on_release('8', self.callback, 8)
        manager.set_wetkey_on_release('9', self.callback, 9)
        manager.register_hotkey([Key.enter, Key.up], None, self.callback, self.ALT_UP)
        manager.register_hotkey([Key.enter, Key.down], None, self.callback, self.ALT_DN)
        manager.register_hotkey([Key.enter, 'a'], None, self.callback, self.ALT_A)
        manager.register_hotkey([Key.enter, 'b'], None, self.callback, self.ALT_B)
        manager.register_hotkey([Key.enter, 'c'], None, self.callback, self.ALT_C)
        manager.register_hotkey([Key.enter, 'd'], None, self.callback, self.ALT_D)
        manager.register_hotkey([Key.enter, '0'], None, self.callback, self.ALT_0)
        manager.register_hotkey([Key.shift, 'a'], None, self.callback, self.LNG_A)
        manager.register_hotkey([Key.shift, 'b'], None, self.callback, self.LNG_B)
        manager.register_hotkey([Key.shift, 'c'], None, self.callback, self.LNG_C)
        manager.register_hotkey([Key.shift, 'd'], None, self.callback, self.LNG_D)
        manager.register_hotkey([Key.shift, Key.enter], None, self.callback, self.LNG_ENT)
        # manager.logger = True

    def callback(self, key):
        self.q.put(key)
