#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import time
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps

RED = (0, 0, 255)


def gamma_correct(in_value):
    in_value = float(in_value) / 255
    out_value = pow(in_value, 0.5)
    out_value = int(255 * out_value)
    return out_value


class UIModule:
    __title__ = "BASE"

    def __init__(self, display, camera_image, shared_state, command_queues):
        self.title = self.__title__
        self.display = display
        self.shared_state = shared_state
        self.camera_image = camera_image
        self.command_queues = command_queues
        self.screen = Image.new("RGB", (128, 128))
        self.draw = ImageDraw.Draw(self.screen)
        self.font_base = ImageFont.truetype(
            "/usr/share/fonts/truetype/Roboto_Mono/static/RobotoMono-Regular.ttf", 10
        )
        self.font_bold = ImageFont.truetype(
            "/usr/share/fonts/truetype/Roboto_Mono/static/RobotoMono-Bold.ttf", 10
        )
        self.font_large = ImageFont.truetype(
            "/usr/share/fonts/truetype/Roboto_Mono/static/RobotoMono-Regular.ttf", 15
        )

    def active(self):
        """
        Called when a module becomes active
        i.e. foreground controlling display
        """
        pass

    def update(self):
        """
        Called to trigger UI Updates
        to be overloaded by subclases and shoud
        end up calling self.screen_update to
        to the actual screen draw
        """
        self.screen_update()

    def screen_update(self):
        """
        called to trigger UI updates
        takes self.screen adds title bar and
        writes to display
        """
        self.draw.rectangle([0, 0, 128, 16], fill=(0, 0, 0))
        self.draw.rounded_rectangle([0, 0, 128, 16], radius=6, fill=(0, 0, 128))
        self.draw.text((6, 1), self.title, font=self.font_bold, fill=(0, 0, 0))

        self.display.display(self.screen.convert(self.display.mode))

    def key_number(self, number):
        pass

    def key_up(self):
        pass

    def key_down(self):
        pass

    def key_enter(self):
        pass

    def key_b(self):
        pass

    def key_c(self):
        pass

    def key_d(self):
        pass


class UIStatus(UIModule):
    """
    Displays various status information
    """

    __title__ = "STATUS"

    def __init__(self, *args):
        self.status_dict = {
            "LST SLV": "--",
            "RA": "--",
            "DEC": "--",
            "AZ": "--",
            "ALT": "--",
            "GPS": "--",
        }
        super().__init__(*args)

    def update_status_dict(self):
        """
        Updates all the
        status dict values
        """
        if self.shared_state.solve_state():
            solution = self.shared_state.solution()
            # last solve time
            self.status_dict["LST SLV"] = str(
                round(time.time() - solution["solve_time"])
            )

            self.status_dict["RA"] = str(round(solution["RA"], 3))
            self.status_dict["DEC"] = str(round(solution["Dec"], 3))

            if solution["Az"]:
                self.status_dict["ALT"] = str(round(solution["Alt"], 3))
                self.status_dict["AZ"] = str(round(solution["Az"], 3))

        location = self.shared_state.location()
        if location["gps_lock"]:
            self.status_dict["GPS"] = "LOCK"

    def update(self):
        self.draw.rectangle([0, 0, 128, 128], fill=(0, 0, 0))
        lines = []
        for k, v in self.status_dict.items():
            line = " " * (7 - len(k)) + k
            line += ":"
            line += " " * (10 - len(v))
            line += v
            lines.append(line)

        for i, line in enumerate(lines):
            self.draw.text((0, i * 10 + 20), line, font=self.font_base, fill=RED)
        self.screen_update()


class UIConsole(UIModule):
    __title__ = "CONSOLE"

    def __init__(self, *args):
        self.dirty = True
        self.lines = ["---- TOP ---"]
        self.scroll_offset = 0
        super().__init__(*args)

    def key_enter(self):
        # reset scroll offset
        self.scroll_offset = 0
        self.dirty = True

    def key_up(self):
        self.scroll_offset += 1
        self.dirty = True

    def key_down(self):
        self.scroll_offset -= 1
        if self.scroll_offset < 0:
            self.scroll_offset = 0
        self.dirty = True

    def write(self, line):
        """
        Writes a new line to the console.
        """
        print(f"Write: {line}")
        self.lines.append(line)
        # reset scroll offset
        self.scroll_offset = 0
        self.dirty = True

    def active(self):
        self.dirty = True
        self.update()

    def update(self):
        # display an image
        if self.dirty:
            # clear screen
            self.draw.rectangle([0, 0, 128, 128], fill=(0, 0, 0))
            for i, line in enumerate(self.lines[-10 - self.scroll_offset :][:10]):
                self.draw.text((0, i * 10 + 20), line, font=self.font_base, fill=RED)
            self.screen_update()
            self.dirty = False


class UIPreview(UIModule):
    __title__ = "PREVIEW"

    def __init__(self, *args):
        self.last_image_update = time.time()
        self.red_image = Image.new("RGB", (128, 128), (0, 0, 255))
        super().__init__(*args)

    def update(self):
        # display an image
        last_image_time = self.shared_state.last_image_time()
        if last_image_time > self.last_image_update:
            image_obj = self.camera_image.copy()
            image_obj = image_obj.resize((128, 128), Image.LANCZOS)
            image_obj = image_obj.convert("RGB")
            image_obj = ImageChops.multiply(image_obj, self.red_image)
            # image_obj = ImageOps.autocontrast(image_obj, cutoff=(20, 0))
            image_obj = Image.eval(image_obj, gamma_correct)
            self.screen.paste(image_obj)
            last_image_fetched = last_image_time

            if self.shared_state.solve_state():
                solution = self.shared_state.solved()
                self.title = "PREVIEW - " + solution["constellation"]
            self.screen_update()

    def key_up(self):
        self.command_queues["camera"].put("exp_up")

    def key_down(self):
        self.command_queues["camera"].put("exp_dn")

    def key_enter(self):
        self.command_queues["camera"].put("exp_save")
