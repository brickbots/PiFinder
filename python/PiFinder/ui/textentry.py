from PIL import Image, ImageDraw, ImageFont
from PiFinder.ui.base import UIModule
from PiFinder.db.db import Database
from PiFinder.db.objects_db import ObjectsDatabase
from PiFinder.ui.object_list import UIObjectList
import time

# class CompositeObjectBuilder:
#
#     def build(self, object_ids: List[int]):
#         return CompositeObject()


class UITextEntry(UIModule):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db: ObjectsDatabase = ObjectsDatabase()
        self.width = 128
        self.height = 128
        self.red = self.colors.get(255)
        self.black = self.colors.get(0)
        self.half_red = self.colors.get(128)
        self.screen = Image.new("RGB", (self.width, self.height), "black")
        self.draw = ImageDraw.Draw(self.screen)
        self.font = ImageFont.load_default()
        self.current_text = ""
        self.last_key = None
        self.key_press_time = 0
        self.char_index = 0
        self.search_objects = []
        self.show_keypad = True
        item_definition = {
                "name": "Results",
                "class": UIObjectList,
                "objects": "custom",
                "object_list": self.search_objects,
                }
        self.object_list = UIObjectList(item_definition=item_definition)
        self.keys = {
            1: "1abc",
            2: "2def",
            3: "3ghi",
            4: "4jkl",
            5: "5mno",
            6: "6pqrs",
            7: "7tuv",
            8: "8wxyz",
            9: "9 '-",
            0: "0",
        }

    def draw_text_entry(self):
        self.draw.line([(5, 30), (100, 30)], fill=self.half_red, width=1)
        self.draw.text((10, 19), self.current_text, font=self.font, fill=self.red)

    def draw_keypad(self):
        keys = [
            ("1", "abc"),
            ("2", "def"),
            ("3", "ghi"),
            ("4", "jkl"),
            ("5", "mno"),
            ("6", "pqrs"),
            ("7", "tuv"),
            ("8", "wxyz"),
            ("9", " '-"),
            # ('*', ''), ('0', ''), ('#', '')
        ]
        key_size = (36, 24)
        padding = 2
        start_x, start_y = 10, 32

        for i, (num, letters) in enumerate(keys):
            x = start_x + (i % 3) * (key_size[0] + padding)
            y = start_y + (i // 3) * (key_size[1] + padding)
            self.draw.rectangle([x, y, x + key_size[0], y + key_size[1]], outline=self.half_red, width=1)
            self.draw.text((x + 2, y + 2), num, font=self.font, fill=self.half_red)
            self.draw.text((x + 2, y + 12), letters, font=self.font, fill=self.half_red)

    def draw_results(self):
        item_definition = {
                "name": "Results",
                "class": UIObjectList,
                "objects": "custom",
                "object_list": self.search_objects,
                }
        self.add_to_stack(item_definition)
        # x, y = 10, 32
        # translated = [(x["id"], x["common_name"]) for x in self.search_results]
        # if translated:
        #     for entry in translated:
        #         self.draw.text((x, y), entry[1], font=self.font, fill=self.red)
        #         y += 10
        # else:
        #     self.draw.text((x, y), "No results", font=self.font, fill=self.red)

    def draw_search_result_len(self):
        self.draw.text(
            (102, 19), str(len(self.search_objects)), font=self.font, fill=self.half_red
        )

    def key_up(self):
        self.show_keypad = not self.show_keypad

    def key_down(self):
        self.key_up()

    def key_square(self):
        self.current_text = self.current_text[:-1]

    def key_number(self, number):
        current_time = time.time()

        # Check if the same key is pressed within a short time
        if self.last_key == number and (current_time - self.key_press_time) < 1:
            self.char_index = (self.char_index + 1) % len(self.keys[number])
            self.current_text = self.current_text[:-1]
        else:
            self.char_index = 0

        self.key_press_time = current_time
        self.last_key = number

        # Get the current character to display
        if number in self.keys:
            char = self.keys[number][self.char_index]
            self.current_text += char
            results = self.catalogs.search_by_text(self.current_text)
            self.search_objects = results
            len_results = len(results)
            print("len_results", len_results)
            self.draw.text((100, 19), str(len_results), font=self.font, fill=self.red)
        else:
            print("didn't find key", number)
            # self.current_text += str(number)

    def update(self, force=False):
        """
        Called to trigger UI Updates
        to be overloaded by subclases and shoud
        end up calling self.screen_update to
        to the actual screen draw
        retun the results of the screen_update to
        pass any signals back to main
        """
        self.draw.rectangle((0, 0, 128, 128), fill=self.colors.get(0))
        self.draw_text_entry()
        self.draw_search_result_len()
        if self.show_keypad:
            self.draw_keypad()
        else:
            self.draw_results()
        # self.display.display(self.screen)
        if self.shared_state:
            self.shared_state.set_screen(self.screen)
        return self.screen_update()
