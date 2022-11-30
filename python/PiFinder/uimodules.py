#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import datetime
import pytz
import time
import os
import uuid
import sqlite3
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps

import solver
from obj_types import OBJ_TYPES
from image_util import gamma_correct_low, subtract_background, red_image
import plot

RED = (0, 0, 255)


class UIModule:
    __title__ = "BASE"
    __uuid__ = str(uuid.uuid1()).split("-")[0]

    def __init__(self, display, camera_image, shared_state, command_queues):
        self.title = self.__title__
        self.switch_to = None
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
            "/usr/share/fonts/truetype/Roboto_Mono/static/RobotoMono-Bold.ttf", 12
        )
        self.font_large = ImageFont.truetype(
            "/usr/share/fonts/truetype/Roboto_Mono/static/RobotoMono-Regular.ttf", 15
        )

        # screenshot stuff
        root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
        prefix = f"{self.__uuid__}_{self.__title__}"
        self.ss_path = os.path.join(root_dir, "screenshots", prefix)
        self.ss_count = 0

    def screengrab(self):
        self.ss_count += 1
        ss_imagepath = self.ss_path + f"_{self.ss_count :0>3}.png"
        ss = self.screen.getchannel("B")
        ss.save(ss_imagepath)

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
        retun the results of the screen_update to
        pass any signals back to main
        """
        return self.screen_update()

    def screen_update(self):
        """
        called to trigger UI updates
        takes self.screen adds title bar and
        writes to display
        """
        self.draw.rectangle([0, 0, 128, 16], fill=(0, 0, 64))
        self.draw.text((6, 1), self.title, font=self.font_bold, fill=(0, 0, 0))
        if self.shared_state:
            if self.shared_state.solve_state():
                solution = self.shared_state.solution()
                constellation = solution["constellation"]
                self.draw.text(
                    (70, 1), constellation, font=self.font_bold, fill=(0, 0, 0)
                )

                # Solver Status
                time_since_solve = time.time() - solution["cam_solve_time"]
                bg = int(64 - (time_since_solve / 6 * 64))
                if bg < 0:
                    bg = 0
                self.draw.rectangle([115, 2, 125, 14], fill=(0, 0, bg))
                self.draw.text(
                    (117, 0),
                    solution["solve_source"][0],
                    font=self.font_bold,
                    fill=(0, 0, 64),
                )
            else:
                # no solve yet....
                self.draw.rectangle([115, 2, 125, 14], fill=(0, 0, 0))
                self.draw.text((117, 0), "X", font=self.font_bold, fill=(0, 0, 64))

            # GPS status
            if self.shared_state.location()["gps_lock"]:
                fg = (0, 0, 0)
                bg = (0, 0, 64)
            else:
                fg = (0, 0, 64)
                bg = (0, 0, 0)
            self.draw.rectangle([100, 2, 110, 14], fill=bg)
            self.draw.text((102, 0), "G", font=self.font_bold, fill=fg)

        self.display.display(self.screen.convert(self.display.mode))

        # We can return a UIModule class name to force a switch here
        tmp_return = self.switch_to
        self.switch_to = None
        return tmp_return

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


class UILocate(UIModule):
    """
    Display pushto info
    """

    __title__ = "LOCATE"

    def __init__(self, *args):
        self.target = None
        self.target_list = []
        self.target_index = None
        self.object_text = ["No Object Found"]
        self.__catalogs = {"N": "NGC", "I": " IC", "M": "Mes"}
        self.sf_utils = solver.Skyfield_utils()
        self.font_huge = ImageFont.truetype(
            "/usr/share/fonts/truetype/Roboto_Mono/static/RobotoMono-Bold.ttf", 35
        )
        super().__init__(*args)

    def key_enter(self):
        """
        When enter is pressed, set the
        target
        """
        self.switch_to = "UICatalog"

    def key_up(self):
        self.scroll_target_history(-1)

    def key_down(self):
        self.scroll_target_history(1)

    def update_object_text(self):
        """
        Generates object text
        """
        if not self.target:
            self.object_text = ["No Object Found"]
            return

        self.object_text = []

        # Type / Constellation
        object_type = OBJ_TYPES.get(self.target["obj_type"], self.target["obj_type"])
        self.object_text.append(f"{object_type: <14} {self.target['const']}")

    def aim_degrees(self):
        """
        Returns degrees in
        az/alt from current position
        to target
        """
        solution = self.shared_state.solution()
        location = self.shared_state.location()
        dt = self.shared_state.datetime()
        if location and dt and solution:
            if solution["Alt"]:
                # We have position and time/date!
                self.sf_utils.set_location(
                    location["lat"],
                    location["lon"],
                    location["altitude"],
                )
                target_alt, target_az = self.sf_utils.radec_to_altaz(
                    self.target["ra"],
                    self.target["dec"],
                    dt,
                )
                az_diff = target_az - solution["Az"]
                az_diff = (az_diff + 180) % 360 - 180

                alt_diff = target_alt - solution["Alt"]
                alt_diff = (alt_diff + 180) % 360 - 180

                return az_diff, alt_diff
        else:
            return None, None

    def active(self):
        state_target = self.shared_state.target()
        if state_target != self.target:
            self.target = state_target
            self.target_list.append(state_target)
            self.target_index = len(self.target_list) - 1
        self.update_object_text()
        self.update()

    def update(self):
        # Clear Screen
        self.draw.rectangle([0, 0, 128, 128], fill=(0, 0, 0))

        if not self.target:
            self.draw.text((0, 20), "No Target Set", font=self.font_large, fill=RED)
            return self.screen_update()

        # Target Name
        line = self.__catalogs.get(self.target["catalog"], "UNK") + " "
        line += str(self.target["designation"])
        self.draw.text((0, 20), line, font=self.font_large, fill=RED)

        # Target history index
        if self.target_index != None:
            line = f"{self.target_index + 1}/{len(self.target_list)}"
            line = f"{line : >7}"
            self.draw.text((85, 20), line, font=self.font_base, fill=RED)

        # ID Line in BOld
        self.draw.text((0, 40), self.object_text[0], font=self.font_bold, fill=RED)

        # Pointing Instructions
        point_az, point_alt = self.aim_degrees()
        if not point_az:
            self.draw.text((0, 50), " ---.-", font=self.font_huge, fill=RED)
            self.draw.text((0, 84), "  --.-", font=self.font_huge, fill=RED)
        else:
            if point_az >= 0:
                self.draw.regular_polygon((10, 75, 10), 3, 90, fill=RED)
                # self.draw.pieslice([-20,65,20,85],330, 30, fill=RED)
                # self.draw.text((0, 50), "+", font=self.font_huge, fill=RED)
            else:
                point_az *= -1
                self.draw.regular_polygon((10, 75, 10), 3, 270, fill=RED)
                # self.draw.pieslice([0,65,40,85],150,210, fill=RED)
                # self.draw.text((0, 50), "-", font=self.font_huge, fill=RED)
            self.draw.text(
                (25, 50), f"{point_az : >5.1f}", font=self.font_huge, fill=RED
            )

            if point_alt >= 0:
                self.draw.regular_polygon((10, 110, 10), 3, 0, fill=RED)
                # self.draw.pieslice([0,84,20,124],60, 120, fill=RED)
                # self.draw.text((0, 84), "+", font=self.font_huge, fill=RED)
            else:
                point_alt *= -1
                self.draw.regular_polygon((10, 105, 10), 3, 180, fill=RED)
                # self.draw.pieslice([0,104,20,144],270, 330, fill=RED)
                # self.draw.text((0, 84), "-", font=self.font_huge, fill=RED)
            self.draw.text(
                (25, 84), f"{point_alt : >5.1f}", font=self.font_huge, fill=RED
            )

        return self.screen_update()

    def scroll_target_history(self, direction):
        if self.target_index != None:
            self.target_index += direction
            if self.target_index >= len(self.target_list):
                self.target_index = len(self.target_list) - 1

            if self.target_index < 0:
                self.target_index = 0

            self.target = self.target_list[self.target_index]
            self.shared_state.set_target(self.target)
            self.update_object_text()
            self.update()


class UICatalog(UIModule):
    """
    Search catalogs for object to find
    """

    __title__ = "CATALOG"

    def __init__(self, *args):
        self.__catalogs = ["NGC", " IC", "Mes"]
        self.catalog_index = 0
        self.designator = ["-"] * 4
        self.cat_object = None
        self.object_text = ["No Object Found"]
        root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
        db_path = os.path.join(root_dir, "astro_data", "pifinder_objects.db")
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.db_c = self.conn.cursor()
        super().__init__(*args)
        self.font_large = ImageFont.truetype(
            "/usr/share/fonts/truetype/Roboto_Mono/static/RobotoMono-Regular.ttf", 20
        )

    def update_object_text(self):
        """
        Generates object text
        """
        if not self.cat_object:
            self.object_text = ["No Object Found", ""]
            return

        # look for AKAs
        aka_recs = self.conn.execute(
            f"""
            SELECT * from names
            where catalog = "{self.cat_object['catalog']}"
            and designation = "{self.cat_object['designation']}"
        """
        ).fetchall()

        self.object_text = []
        # Type / Constellation
        object_type = OBJ_TYPES.get(
            self.cat_object["obj_type"], self.cat_object["obj_type"]
        )
        self.object_text.append(f"{object_type: <14} {self.cat_object['const']}")

        # Magnitude / Size
        self.object_text.append(
            f"Mag:{self.cat_object['mag'] : <4}"
            + " " * 3
            + f"Sz:{self.cat_object['size']}"
        )

        if aka_recs:
            aka_list = []
            for rec in aka_recs:
                if rec["common_name"].startswith("M"):
                    aka_list.insert(0, rec["common_name"])
                else:
                    aka_list.append(rec["common_name"])
            self.object_text.append(", ".join(aka_list))

        # NGC description....
        max_line = 20
        line = ""
        desc_tokens = self.cat_object["desc"].split(" ")
        for token in desc_tokens:
            if len(line) + len(token) + 1 > max_line:
                self.object_text.append(line)
                line = token
            else:
                line = line + " " + token

    def active(self):
        target = self.shared_state.target()
        if target:
            self.cat_object = target
            self.catalog_index = ["N", "I", "M"].index(target["catalog"])
            self.designator = list(str(target["designation"]))
            if self.catalog_index == 2:
                self.designator = ["-"] * (3 - len(self.designator)) + self.designator
            else:
                self.designator = ["-"] * (4 - len(self.designator)) + self.designator

        self.update_object_text()
        self.update()

    def update(self):
        # Clear Screen
        self.draw.rectangle([0, 0, 128, 128], fill=(0, 0, 0))

        # catalog and entry field
        line = self.__catalogs[self.catalog_index] + " "
        line += "".join(self.designator)
        self.draw.text((0, 21), line, font=self.font_large, fill=RED)

        # ID Line in BOld
        self.draw.text((0, 48), self.object_text[0], font=self.font_bold, fill=RED)
        # mag/size in bold
        self.draw.text((0, 62), self.object_text[1], font=self.font_bold, fill=RED)

        # Remaining lines
        for i, line in enumerate(self.object_text[2:]):
            self.draw.text((0, i * 11 + 82), line, font=self.font_base, fill=RED)
        return self.screen_update()

    def key_d(self):
        # d is for delete
        if self.catalog_index == 2:
            # messier
            self.designator = ["-"] * 3
        else:
            self.designator = ["-"] * 4
        self.cat_object = None
        self.update_object_text()

    def key_c(self):
        # C is for catalog
        self.catalog_index += 1
        if self.catalog_index >= len(self.__catalogs):
            self.catalog_index = 0
        if self.catalog_index == 2:
            # messier
            self.designator = ["-"] * 3
        else:
            self.designator = ["-"] * 4
        self.cat_object = None
        self.update_object_text()

    def key_number(self, number):
        self.designator = self.designator[1:]
        self.designator.append(str(number))
        if self.designator[0] in ["0", "-"]:
            index = 0
            go = True
            while go:
                self.designator[index] = "-"
                index += 1
                if index >= len(self.designator) or self.designator[index] not in [
                    "0",
                    "-",
                ]:
                    go = False
        # Check for match
        designator = "".join(self.designator).replace("-", "")
        catalog = self.__catalogs[self.catalog_index].strip()[0]
        self.cat_object = self.conn.execute(
            f"""
            SELECT * from objects
            where catalog = "{catalog}"
            and designation = "{designator}"
        """
        ).fetchone()
        self.update_object_text()

    def key_enter(self):
        """
        When enter is pressed, set the
        target
        """
        if self.cat_object:
            self.shared_state.set_target(dict(self.cat_object))
            self.switch_to = "UILocate"

    def scroll_obj(self, direction):
        """
        Looks for the next object up/down
        sets the designation and object
        """
        if direction == "<":
            sort_order = "desc"
        else:
            sort_order = ""

        designator = "".join(self.designator).replace("-", "")
        catalog = self.__catalogs[self.catalog_index].strip()[0]

        tmp_obj = self.conn.execute(
            f"""
            SELECT * from objects
            where catalog = "{catalog}"
            and designation {direction} "{designator}"
            order by designation {sort_order}
        """
        ).fetchone()

        if tmp_obj:
            self.cat_object = tmp_obj
            desig = str(tmp_obj["designation"])
            desig = list(desig)
            if self.catalog_index == 2:
                desig = ["-"] * (3 - len(desig)) + desig
            else:
                desig = ["-"] * (4 - len(desig)) + desig

            self.designator = desig
            self.update_object_text()

    def key_up(self):
        self.scroll_obj("<")

    def key_down(self):
        self.scroll_obj(">")


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
            "IMU": "--",
            "IMU PS": "--",
            "LCL TM": "--",
            "UTC TM": "--",
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
            self.status_dict["LST SLV"] = (
                str(round(time.time() - solution["solve_time"]))
                + " - "
                + str(solution["solve_source"])
            )

            self.status_dict["RA"] = str(round(solution["RA"], 3))
            self.status_dict["DEC"] = str(round(solution["Dec"], 3))

            if solution["Az"]:
                self.status_dict["ALT"] = str(round(solution["Alt"], 3))
                self.status_dict["AZ"] = str(round(solution["Az"], 3))

        location = self.shared_state.location()
        if location["gps_lock"]:
            self.status_dict["GPS"] = "LOCK"

        imu = self.shared_state.imu()
        if imu:
            self.status_dict["IMU"] = str(imu["moving"]) + " " + str(imu["status"])
            self.status_dict["IMU PS"] = f"{imu['pos'][0] :.1f} {imu['pos'][1] :.1f}"

        dt = self.shared_state.datetime()
        if dt:
            utc_tz = pytz.timezone("UTC")
            dt = utc_tz.localize(dt)
            local_tz = pytz.timezone(location["timezone"])
            self.status_dict["LCL TM"] = dt.astimezone(local_tz).time().isoformat()
            self.status_dict["UTC TM"] = dt.time().isoformat()

    def update(self):
        self.update_status_dict()
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
        return self.screen_update()


class UIConsole(UIModule):
    __title__ = "CONSOLE"

    def __init__(self, *args):
        self.dirty = True
        self.lines = ["---- TOP ---"]
        self.scroll_offset = 0
        self.debug_mode = False
        super().__init__(*args)

    def set_shared_state(self, shared_state):
        self.shared_state = shared_state

    def key_number(self, number):
        if number == 0:
            self.command_queues["camera"].put("debug")
            if self.debug_mode:
                self.debug_mode = False
            else:
                self.debug_mode = True
            self.command_queues["console"].put("Debug: " + str(self.debug_mode))
        dt = datetime.datetime(2022, 11, 15, 2, 0, 0)
        self.shared_state.set_datetime(dt)

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
            self.dirty = False
            return self.screen_update()


class UIPreview(UIModule):
    __title__ = "PREVIEW"

    def __init__(self, *args):
        self.preview_modes = ["image", "plot", "plot+const"]
        self.preview_index = 0
        self.reticle_mode = 2
        self.last_update = time.time()
        self.starfield = plot.Starfield()
        self.solution = None
        super().__init__(*args)

    def plot_target(self):
        """
        Plot the target....
        """
        # is there a target?
        target = self.shared_state.target()
        if not target or not self.solution:
            return

        marker_list = [
            (plot.Angle(degrees=target["ra"])._hours, target["dec"], "target")
        ]

        marker_image = self.starfield.plot_markers(
            self.solution["RA"],
            self.solution["Dec"],
            self.solution["Roll"],
            marker_list,
        )
        self.screen.paste(ImageChops.add(self.screen, marker_image))

    def draw_reticle(self):
        """
        draw the reticle if desired
        """
        if self.reticle_mode == 0:
            # None....
            return

        brightness = 64
        if self.reticle_mode == 1:
            brightness = 32

        bboxes = [
            [39, 39, 89, 89],
            [52, 52, 76, 76],
            [61, 61, 67, 67],
        ]
        for bbox in bboxes:
            self.draw.arc(bbox, 20, 70, fill=(0, 0, brightness))
            self.draw.arc(bbox, 110, 160, fill=(0, 0, brightness))
            self.draw.arc(bbox, 200, 250, fill=(0, 0, brightness))
            self.draw.arc(bbox, 290, 340, fill=(0, 0, brightness))

    def update(self, force=False):
        if force:
            self.last_update = 0
        preview_mode = self.preview_modes[self.preview_index]
        if preview_mode == "image":
            # display an image
            last_image_time = self.shared_state.last_image_time()[1]
            if last_image_time > self.last_update:
                image_obj = self.camera_image.copy()
                image_obj = image_obj.resize((128, 128), Image.LANCZOS)
                image_obj = subtract_background(image_obj)
                image_obj = image_obj.convert("RGB")
                image_obj = ImageChops.multiply(image_obj, red_image)
                image_obj = ImageOps.autocontrast(image_obj)
                image_obj = Image.eval(image_obj, gamma_correct_low)
                self.screen.paste(image_obj)
                if self.shared_state.solve_state():
                    self.solution = self.shared_state.solution()
                    self.plot_target()
                self.last_update = last_image_time

                self.title = "PREVIEW"

        if preview_mode.startswith("plot"):
            # display plot
            show_const = False
            if preview_mode.endswith("const"):
                show_const = True

            if self.shared_state.solve_state():
                self.solution = self.shared_state.solution()
                last_solve_time = self.solution["solve_time"]
                if (
                    last_solve_time > self.last_update
                    and self.solution["Roll"] != None
                    and self.solution["RA"] != None
                    and self.solution["Dec"] != None
                ):
                    image_obj = self.starfield.plot_starfield(
                        self.solution["RA"],
                        self.solution["Dec"],
                        self.solution["Roll"],
                        show_const,
                    )
                    image_obj = ImageChops.multiply(image_obj, red_image)
                    self.screen.paste(image_obj)
                    self.plot_target()
                    self.last_update = last_solve_time

            else:
                self.title = "PLOT"
                self.draw.rectangle([0, 0, 128, 128], fill=(0, 0, 0))
                self.draw.text((18, 20), "Can't plot", font=self.font_large, fill=RED)
                self.draw.text((25, 50), "No Solve Yet", font=self.font_base, fill=RED)
                # set preview index to end of plots
                # so the next button press will get out
                # of plots
                self.preview_index = 2

        self.draw_reticle()
        return self.screen_update()

    def key_b(self):
        self.preview_index += 1
        if self.preview_index >= len(self.preview_modes):
            self.preview_index = 0
        self.update(force=True)

    def key_c(self):
        self.reticle_mode += 1
        if self.reticle_mode > 2:
            self.reticle_mode = 0
        self.update(force=True)

    def key_up(self):
        self.command_queues["camera"].put("exp_up")

    def key_down(self):
        self.command_queues["camera"].put("exp_dn")

    def key_enter(self):
        self.command_queues["camera"].put("exp_save")
