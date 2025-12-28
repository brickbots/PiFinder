from PIL import Image, ImageDraw
from PiFinder.ui.base import UIModule
from PiFinder.db.objects_db import ObjectsDatabase
from PiFinder.ui.object_list import UIObjectList
from PiFinder.ui.ui_utils import format_number
import time
import threading
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:

    def _(a) -> Any:
        return a

# class CompositeObjectBuilder:
#
#     def build(self, object_ids: List[int]):
#         return CompositeObject()


class KeyPad:
    def __init__(self):
        self.base = {
            "7": ("7abc", "abc"),
            "8": ("8def", "def"),
            "9": ("9ghi", "ghi"),
            "4": ("4jkl", "jkl"),
            "5": ("5mno", "mno"),
            "6": ("6pqrs", "pqrs"),
            "1": ("1tuv", "tuv"),
            "2": ("2wxyz", "wxyz"),
            "3": ("3'-+/", "'-+/"),
            "+": ("", "Space"),
            "0": ("0", ""),
            "-": ("", "Del"),
        }
        self.symbols = {
            "7": ("7&()", "&()"),
            "8": ("8,.;", ",.;"),
            "9": ("9:=?", ":=?"),
            "4": ("4", ""),
            "5": ("5", ""),
            "6": ("6", ""),
            "1": ("1", ""),
            "2": ("2", ""),
            "3": ("3", ""),
            "+": ("", "Space"),
            "0": ("0", ""),
            "-": ("", "Del"),
        }
        self.keys = self.base

    def get_char(self, key, index):
        if key in self.keys:
            return self.keys[key][0][index % len(self.keys[key][0])]
        return None

    def get_display(self, key):
        if key in self.keys:
            return self.keys[key][1]
        return None

    def get_nr_entries(self, key):
        if key in self.keys:
            return len(self.keys[key][0])
        return 0

    def switch_keys(self):
        if self.keys == self.base:
            self.keys = self.symbols
        else:
            self.keys = self.base

    def __contains__(self, key):
        return key in self.keys

    def __iter__(self):
        for key, value in self.keys.items():
            yield key, value


class UITextEntry(UIModule):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Get mode from item_definition
        self.text_entry_mode = self.item_definition.get("mode") == "text_entry"
        self.current_text = self.item_definition.get("initial_text", "")
        self.callback = self.item_definition.get("callback")

        self.width = 128
        self.height = 128
        self.red = self.colors.get(255)
        self.black = self.colors.get(0)
        self.half_red = self.colors.get(128)
        self.screen = Image.new("RGB", (self.width, self.height), "black")
        self.draw = ImageDraw.Draw(self.screen)
        self.bold = self.fonts.bold

        # Only initialize database if we're in search mode
        if not self.text_entry_mode:
            self.db: ObjectsDatabase = ObjectsDatabase()

        self.last_key = None
        self.KEYPRESS_TIMEOUT = 1
        self.last_key_press_time = 0
        self.char_index = 0
        self.search_results = []
        self.search_results_len_str = "0"
        self.show_keypad = True
        self.keys = KeyPad()
        self.cursor_width = self.fonts.bold.width
        self.cursor_height = self.fonts.bold.height
        self.text_x = 7
        self.text_x_end = 128 - self.text_x
        self.text_y = self.display_class.titlebar_height + 2

        # Async search state
        self._search_timer = None
        self._search_version = 0
        self._search_lock = threading.Lock()
        self._results_updated = False  # Flag to trigger UI refresh
        self.SEARCH_DEBOUNCE_MS = 250  # milliseconds

    def draw_text_entry(self):
        line_text_y = self.text_y + 15
        self.draw.line(
            [(self.text_x, line_text_y), (self.text_x_end, line_text_y)],
            fill=self.half_red,
            width=1,
        )
        self.draw.text(
            (self.text_x, self.text_y),
            self.current_text,
            font=self.bold.font,
            fill=self.red,
        )
        # Calculate cursor position
        cursor_x = self.text_x + self.bold.font.getbbox(self.current_text)[2]
        cursor_y = self.text_y

        # Draw inverted block cursor
        if self.within_keypress_window(time.time()) and self.current_text:
            char = self.current_text[-1]
            self.draw.rectangle(
                [
                    cursor_x - self.cursor_width,
                    cursor_y,
                    cursor_x,
                    cursor_y + self.cursor_height,
                ],
                fill=self.red,
            )
            self.draw.text(
                (cursor_x - self.cursor_width, cursor_y),
                char,
                font=self.bold.font,
                fill=self.black,
            )
        else:
            self.draw.rectangle(
                [
                    cursor_x,
                    cursor_y,
                    cursor_x + self.cursor_width,
                    cursor_y + self.cursor_height,
                ],
                fill=self.red,
            )

    def draw_keypad(self):
        key_size = (38, 23)
        padding = 0
        start_x, start_y = self.text_x, 32

        for i, (num, letters) in enumerate(self.keys):
            x = start_x + (i % 3) * (key_size[0] + padding)
            y = start_y + (i // 3) * (key_size[1] + padding)
            self.draw.rectangle(
                [x, y, x + key_size[0], y + key_size[1]], outline=self.half_red, width=1
            )
            self.draw.text(
                (x + 2, y), str(num), font=self.fonts.base.font, fill=self.half_red
            )
            self.draw.text(
                (x + 2, y + 8),
                letters[1],
                font=self.fonts.bold.font,
                fill=self.colors.get(192),
            )

    def draw_results(self):
        # Thread-safe read of search results
        with self._search_lock:
            results = self.search_results.copy()

        item_definition = {
            "name": _("Results"),
            "class": UIObjectList,
            "objects": "custom",
            "object_list": results,
        }
        self.add_to_stack(item_definition)

    def draw_search_result_len(self):
        # Thread-safe read of search results length
        with self._search_lock:
            result_count = len(self.search_results)

        formatted_len = format_number(result_count, 4).strip()
        self.text_x_end = (
            128 - 2 - self.text_x - self.bold.font.getbbox(formatted_len)[2]
        )
        self.draw.text(
            (self.text_x_end + 2, self.text_y),
            formatted_len,
            font=self.bold.font,
            fill=self.half_red,
        )

    def within_keypress_window(self, current_time) -> bool:
        result = (current_time - self.last_key_press_time) < self.KEYPRESS_TIMEOUT
        return result and self.keys.get_nr_entries(str(self.last_key)) > 1

    def update_search_results(self):
        """
        Debounced async search - waits 250ms after last keystroke before searching.
        Only updates search results in search mode.
        """
        import logging

        logger = logging.getLogger("TextEntry")

        if self.text_entry_mode:
            logger.info("update_search_results: in text_entry_mode, returning")
            return

        logger.info(
            f"update_search_results: scheduling search for '{self.current_text}'"
        )

        # Cancel pending timer if exists
        if self._search_timer is not None:
            self._search_timer.cancel()
            logger.info("update_search_results: cancelled pending timer")

        # Increment search version to invalidate any in-flight searches
        with self._search_lock:
            self._search_version += 1
            current_version = self._search_version

        # Capture current search text (don't reference self.current_text in lambda)
        search_text = self.current_text

        # Schedule search after debounce delay
        self._search_timer = threading.Timer(
            self.SEARCH_DEBOUNCE_MS / 1000.0,
            lambda: self._perform_search(search_text, current_version),
        )
        self._search_timer.start()
        logger.info(
            f"update_search_results: timer started for 250ms, version={current_version}"
        )

    def _perform_search(self, search_text, search_version):
        """
        Perform the actual search in background thread.
        Only updates results if this search version is still current.
        """
        import logging

        logger = logging.getLogger("TextEntry")

        try:
            logger.info(
                f"_perform_search called with text='{search_text}', version={search_version}"
            )

            # Search through whatever catalogs are loaded
            # Priority catalogs (NGC, IC, M) are loaded first, WDS loads in background
            # So search will work immediately with those, WDS results appear when loading completes
            logger.info(f"Starting search for '{search_text}'")
            results = self.catalogs.search_by_text(search_text)
            logger.info(f"Search for '{search_text}' found {len(results)} results")

            # Only update if this search is still current (not superseded by newer search)
            with self._search_lock:
                if search_version == self._search_version:
                    self.search_results = results
                    self._results_updated = True  # Flag that we need UI refresh
                    logger.info("Search results updated, flagging UI refresh")
                else:
                    logger.info(
                        f"Search results discarded (version mismatch: {search_version} != {self._search_version})"
                    )
        except Exception as e:
            logger.error(f"Exception in _perform_search: {e}", exc_info=True)

    def add_char(self, char):
        if len(self.current_text) >= 12:
            return
        self.current_text += char
        self.update_search_results()

    def delete_last_char(self):
        self.current_text = self.current_text[:-1]
        self.update_search_results()

    def key_left(self):
        """Handle left key based on mode"""
        if self.text_entry_mode:
            # Pure text entry mode - confirm and return
            if self.callback:
                self.callback(self.current_text)
                return True
        else:
            # Search mode - if showing results, return to keypad view
            # Otherwise pop from stack
            if not self.show_keypad:
                self.show_keypad = True
                return False
            else:
                return True

    def key_right(self):
        """Handle right key based on mode"""
        if not self.text_entry_mode:
            # Search mode - show results
            self.draw_results()

    def key_square(self):
        self.keys.switch_keys()

    def key_plus(self):
        self.add_char(" ")

    def key_minus(self):
        self.delete_last_char()

    def key_long_minus(self):
        self.current_text = ""
        self.update_search_results()

    def key_number(self, number):
        current_time = time.time()
        number_key = str(number)
        # Check if the same key is pressed within a short time
        if self.last_key == number and self.within_keypress_window(current_time):
            self.char_index = (self.char_index + 1) % self.keys.get_nr_entries(
                number_key
            )
            self.delete_last_char()
        else:
            self.char_index = 0
        self.last_key_press_time = current_time
        self.last_key = number

        # Get the current character to display
        if number_key in self.keys:
            char = self.keys.get_char(number_key, self.char_index)
            if char == "X":
                self.delete_last_char()
                return
            self.add_char(char)
        else:
            print("didn't find key", number_key)

    def inactive(self):
        """Cancel/invalidate any in-flight searches when screen becomes inactive"""
        # Cancel pending timer
        if self._search_timer is not None:
            self._search_timer.cancel()
            self._search_timer = None

        # Increment version to make any running searches ignore their results
        with self._search_lock:
            self._search_version += 1

    def update(self, force=False):
        self.draw.rectangle((0, 0, 128, 128), fill=self.colors.get(0))

        # Set title based on mode (will be drawn by screen_update())
        if self.text_entry_mode:
            self.title = _("Enter Location Name:")
        else:
            self.title = _("Search")
            self.draw_search_result_len()

        self.draw_text_entry()

        # Always show keypad in pure text entry mode
        # In search mode, toggle between keypad and results
        if self.text_entry_mode or self.show_keypad:
            self.draw_keypad()
        else:
            self.draw_results()

        return self.screen_update()
