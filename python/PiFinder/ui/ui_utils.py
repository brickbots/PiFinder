import PiFinder.utils as utils
from PiFinder import calc_utils
from PiFinder.ui.fonts import Fonts as fonts
from typing import Tuple, List, Dict, Optional
import textwrap
import logging
from pathlib import Path
import sqlite3
from PiFinder import obslog
import time
import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree


class Catalog:
    """Keeps catalog data + keeps track of current catalog/object"""

    last_filtered: float = 0

    def __init__(self, catalog_name):
        self.catalog_name = catalog_name
        self.objects = {}
        self.objects_keys_sorted = []
        self.filtered_objects = {}
        self.filtered_objects_keys_sorted = []
        self._load_catalog()

    def get_count(self):
        return len(self.objects)

    def get_filtered_count(self):
        return len(self.filtered_objects)

    def _load_catalog(self):
        """
        Loads all catalogs into memory

        """
        self.conn = sqlite3.connect(utils.pifinder_db)
        self.conn.row_factory = sqlite3.Row
        logging.debug("loading " + self.catalog_name)
        cat_objects = self.conn.execute(
            f"""
            SELECT * from objects
            where catalog='{self.catalog_name}'
            order by sequence
        """
        ).fetchall()
        self.objects = {dict(row)["sequence"]: dict(row) for row in cat_objects}
        self.objects_keys_sorted = self._get_sorted_keys(self.objects)
        logging.info(f"loaded {len(self.objects)} objects for {self.catalog_name}")
        self.conn.close()

    def _get_sorted_keys(self, dictionary):
        return sorted(dictionary.keys())

    def filter(
        self,
        shared_state,
        magnitude_filter,
        type_filter,
        altitude_filter,
        observed_filter,
    ):
        """
        Does filtering based on params
        populates self._filtered_catalog
        from in-memory catalogs
        does not try to maintain current index because it has no notion of that
        should be done in catalog.py
        """
        self.last_filtered = time.time()

        self.filtered_objects = {}

        fast_aa = None
        if altitude_filter != "None":
            # setup
            solution = shared_state.solution()
            location = shared_state.location()
            dt = shared_state.datetime()
            if location and dt and solution:
                fast_aa = calc_utils.FastAltAz(
                    location["lat"],
                    location["lon"],
                    dt,
                )

        if observed_filter != "Any":
            # setup
            observed_list = obslog.get_observed_objects()

        for key, obj in self.objects.items():
            # print(f"filtering {obj}")
            include_obj = True

            # try to get object mag to float
            try:
                obj_mag = float(obj["mag"])
            except (ValueError, TypeError):
                obj_mag = 99

            if magnitude_filter != "None" and obj_mag >= magnitude_filter:
                include_obj = False

            if type_filter != ["None"] and obj["obj_type"] not in type_filter:
                include_obj = False

            if fast_aa:
                obj_altitude = fast_aa.radec_to_altaz(
                    obj["ra"],
                    obj["dec"],
                    alt_only=True,
                )
                if obj_altitude < altitude_filter:
                    include_obj = False

            if observed_filter != "Any":
                if (obj["catalog"], obj["sequence"]) in observed_list:
                    if observed_filter == "No":
                        include_obj = False
                else:
                    if observed_filter == "Yes":
                        include_obj = False

            if include_obj:
                self.filtered_objects[key] = obj
        self.filtered_objects_keys_sorted = self._get_sorted_keys(self.filtered_objects)


class CatalogDesignator:
    """Holds the string that represents the catalog input/search field.
    Usually looks like 'NGC----' or 'M-13'"""

    def __init__(self, catalog_name):
        self.catalog_name = catalog_name
        self.object_number = 0
        self.field = self.get_designator()

    def set_target(self, catalog_index, number=0):
        assert len(str(number)) <= self.get_catalog_width()
        self.catalog_index = catalog_index
        self.object_number = number
        self.field = self.get_designator()

    def append_number(self, number):
        number_str = str(self.object_number) + str(number)
        if len(number_str) > self.get_catalog_width():
            number_str = number_str[1:]
        self.object_number = int(number_str)
        self.field = self.get_designator()

    def set_number(self, number):
        self.object_number = number
        self.field = self.get_designator()

    def has_number(self):
        return self.object_number > 0

    def reset_number(self):
        self.object_number = 0
        self.field = self.get_designator()

    def increment_number(self):
        self.object_number += 1
        self.field = self.get_designator()

    def decrement_number(self):
        self.object_number -= 1
        self.field = self.get_designator()

    def get_catalog_name(self):
        return self.catalog_name

    def get_catalog_width(self):
        return CAT_DASHES[self.get_catalog_name()]

    def get_designator(self):
        number_str = str(self.object_number) if self.has_number() else ""
        return (
            f"{self.get_catalog_name(): >3} {number_str:->{self.get_catalog_width()}}"
        )

    def __str__(self):
        return self.field

    def __repr__(self):
        return self.field


class CatalogTracker:
    object_tracker: Dict[str, Optional[int]]
    designator_tracker: Dict[str, Optional[CatalogDesignator]]
    current: Catalog
    current_catalog_name: str

    def __init__(self, catalog_names: List[str], shared_state, config_options):
        self.catalog_names = catalog_names
        self.shared_state = shared_state
        self.config_options = config_options
        self.catalogs: Dict[str, Catalog] = self._load_catalogs(catalog_names)
        self.designator_tracker = {c: CatalogDesignator(c) for c in self.catalog_names}
        self.set_current_catalog(catalog_names[0])
        self.object_tracker = {c: None for c in self.catalog_names}

    def set_current_catalog(self, catalog_name):
        assert catalog_name in self.catalogs
        self.current = self.catalogs[catalog_name]
        self.current_catalog_name = catalog_name

    def next_catalog(self, direction=1):
        current_index = self.catalog_names.index(self.current_catalog_name)
        next_index = (current_index + direction) % len(self.catalog_names)
        self.set_current_catalog(self.catalog_names[next_index])

    def previous_catalog(self):
        self.next_catalog(-1)

    def next_object(self, direction=1, filtered=True):
        keys_sorted = (
            self.current.filtered_objects_keys_sorted
            if filtered
            else self.current.objects_keys_sorted
        )
        current_key = self.object_tracker[self.current_catalog_name]
        designator = self.get_designator()
        if current_key is None:
            next_index = 0 if direction == 1 else len(keys_sorted) - 1
            next_key = keys_sorted[next_index]
            designator.set_number(next_key)

        else:
            current_index = keys_sorted.index(current_key) if current_key != -1 else -1
            next_index = (current_index + direction) % len(keys_sorted)
            next_key = keys_sorted[next_index]
            if next_index == 0:
                next_key = None  # hack to get around the fact that 0 is a valid key
                designator.set_number(0)  # todo use -1 in designator as well
            else:
                designator.set_number(next_key)
        self.set_current_object(next_key)
        return self.get_current_object()

    def previous_object(self):
        return self.next_object(-1)

    def get_objects(self, catalogs=None):
        catalog_list = self._select_catalogs(catalogs)
        return [catalog.objects for catalog in catalog_list]

    def does_filtered_have_current_object(self):
        return (
            self.object_tracker[self.current_catalog_name]
            in self.current.filtered_objects
        )

    def get_current_object(self):
        object_key = self.object_tracker[self.current_catalog_name]
        if object_key is None:
            return None
        return self.current.objects[object_key]

    def set_current_object(self, object_number, catalog_name=None):
        catalog_name = self._get_catalog_name(catalog_name)
        self.current_catalog_name = catalog_name
        self.object_tracker[catalog_name] = object_number
        self.designator_tracker[catalog_name].set_number(
            object_number if object_number else 0
        )

    def get_designator(self, catalog_name=None) -> CatalogDesignator:
        catalog_name = self._get_catalog_name(catalog_name)
        return self.designator_tracker[catalog_name]

    def _load_catalogs(self, catalogs: List[str]) -> Dict[str, Catalog]:
        result = {}
        for catalog in catalogs:
            result[catalog] = Catalog(catalog)
        return result

    def _get_catalog_name(self, catalog: Optional[str]) -> str:
        catalog = catalog or self.current_catalog_name
        return catalog

    def _select_catalog(self, catalog: Optional[str]) -> Catalog:
        catalog = self._get_catalog_name(catalog)
        return self.catalogs.get(catalog)

    def _select_catalogs(self, catalogs: Optional[List[str]]) -> List[Catalog]:
        if catalogs is None:
            catalog_list = [self.current]
        else:
            catalog_list = [self.catalogs.get(key) for key in catalogs]
        return catalog_list

    def filter(self, catalogs=None):
        catalog_list: List[Catalog] = self._select_catalogs(catalogs=catalogs)
        magnitude_filter = self.config_options["Magnitude"]["value"]
        type_filter = self.config_options["Obj Types"]["value"]
        altitude_filter = self.config_options["Alt Limit"]["value"]
        observed_filter = self.config_options["Observed"]["value"]

        for catalog in catalog_list:
            catalog.filter(
                self.shared_state,
                magnitude_filter,
                type_filter,
                altitude_filter,
                observed_filter,
            )
        if self.current not in catalog_list:
            self.current.filter(
                self.shared_state,
                magnitude_filter,
                type_filter,
                altitude_filter,
                observed_filter,
            )

    def get_closest_objects(self, ra, dec, n, catalogs=None):
        """
        Takes the current catalog or a list of catalogs, gets the filtered
        objects and returns the n closest objects to ra/dec
        """
        catalog_list: List[Catalog] = self._select_catalogs(catalogs=catalogs)
        catalog_list_flat = [x for y in catalog_list for x in y.filtered_objects]
        object_ras = [np.deg2rad(x["ra"]) for x in catalog_list_flat]
        object_decs = [np.deg2rad(x["dec"]) for x in catalog_list_flat]

        objects_df = pd.DataFrame(
            {
                "ra": object_ras,
                "dec": object_decs,
            }
        )
        objects_bt = BallTree(
            objects_df[["ra", "dec"]], leaf_size=4, metric="haversine"
        )

        query_df = pd.DataFrame({"ra": [np.deg2rad(ra)], "dec": [np.deg2rad(dec)]})
        _dist, obj_ind = objects_bt.query(query_df, k=n)
        return [catalog_list_flat[x] for x in obj_ind[0]]

    def __repr__(self):
        return f"CatalogTracker({self.catalog_names}), {self.current_catalog_name=}, {self.object_tracker=}, {self.designator_tracker=})"


class SpaceCalculator:
    """Calculates spaces for proportional fonts, obsolete"""

    def __init__(self, draw, width):
        self.draw = draw
        self.width = width
        pass

    def _calc_string(self, left, right, spaces) -> str:
        return f"{left}{'':.<{spaces}}{right}"

    def calculate_spaces(self, left, right) -> Tuple[int, str]:
        """
        returns number of spaces
        """
        spaces = 1
        if self.draw.textlength(self._calc_string(left, right, spaces)) > self.width:
            return -1, ""

        while self.draw.textlength(self._calc_string(left, right, spaces)) < self.width:
            spaces += 1

        spaces = spaces - 1

        result = self._calc_string(left, right, spaces)
        # logging.debug(f"returning {spaces=}, {result=}")
        return spaces, result


class SpaceCalculatorFixed:
    """Calculates spaces for fixed-width fonts"""

    def __init__(self, nr_chars):
        self.width = nr_chars

    def _calc_string(self, left, right, spaces) -> str:
        return f"{left}{'': <{spaces}}{right}"

    def calculate_spaces(self, left: str, right: str) -> Tuple[int, str]:
        """
        returns number of spaces
        """
        spaces = 1
        lenleft = len(str(left))
        lenright = len(str(right))

        if lenleft + lenright + 1 > self.width:
            return -1, ""

        spaces = self.width - (lenleft + lenright)
        result = self._calc_string(left, right, spaces)
        return spaces, result


# determine what the highest sequence nr of a catalog is,
# so we can determine the nr of dashes to show
def create_catalog_sizes():
    # open the DB
    conn = sqlite3.connect(utils.pifinder_db)
    conn.row_factory = sqlite3.Row
    db_c = conn.cursor()
    query = "SELECT catalog, MAX(sequence) FROM objects GROUP BY catalog"
    db_c.execute(query)
    result = db_c.fetchall()
    conn.close()
    return {row["catalog"]: len(str(row["MAX(sequence)"])) for row in result}


CAT_DASHES = create_catalog_sizes()


class TextLayouterSimple:
    def __init__(
        self,
        text: str,
        draw,
        color,
        font=fonts.base,
        width=fonts.base_width,
    ):
        self.text = text
        self.font = font
        self.color = color
        self.width = width
        self.drawobj = draw
        self.object_text: List[str] = []
        self.updated = True

    def set_text(self, text):
        self.text = text
        self.updated = True

    def set_color(self, color):
        self.color = color
        self.updated = True

    def layout(self, pos: Tuple[int, int] = (0, 0)):
        if self.updated:
            self.object_text: List[str] = [self.text]
            self.updated = False

    def draw(self, pos: Tuple[int, int] = (0, 0)):
        self.layout(pos)
        # logging.debug(f"Drawing {self.object_text=}")
        self.drawobj.multiline_text(
            pos, "\n".join(self.object_text), font=self.font, fill=self.color, spacing=0
        )

    def __repr__(self):
        return f"TextLayouterSimple({self.text=}, {self.color=}, {self.font=}, {self.width=})"


class TextLayouterScroll(TextLayouterSimple):
    """To be used as a one-line scrolling text"""

    FAST = 750
    MEDIUM = 500
    SLOW = 200

    def __init__(
        self,
        text: str,
        draw,
        color,
        font=fonts.base,
        width=fonts.base_width,
        scrollspeed=MEDIUM,
    ):
        self.pointer = 0
        self.textlen = len(text)
        self.updated = True

        if self.textlen >= width:
            self.dtext = text + " " * 6 + text
            self.dtextlen = len(self.dtext)
            self.counter = 0
            self.counter_max = 3000
            self.set_scrollspeed(scrollspeed)
        super().__init__(text, draw, color, font, width)

    def set_scrollspeed(self, scrollspeed: float):
        self.scrollspeed = float(scrollspeed)
        self.counter = 0

    def layout(self, pos: Tuple[int, int] = (0, 0)):
        if self.textlen > self.width and self.scrollspeed > 0:
            if self.counter == 0:
                self.object_text: List[str] = [
                    self.dtext[self.pointer : self.pointer + self.width]
                ]
                self.pointer = (self.pointer + 1) % (self.textlen + 6)
            # start goes slower
            if self.pointer == 1:
                self.counter = (self.counter + 100) % self.counter_max
            # regular scrolling
            else:
                self.counter = (self.counter + self.scrollspeed) % self.counter_max
        elif self.updated:
            self.object_text: List[str] = [self.text]
            self.updated = False


class TextLayouter(TextLayouterSimple):
    """To be used as a multi-line text with down scrolling"""

    shorttop = [48, 125, 80, 125]
    shortbottom = [48, 126, 80, 126]
    longtop = [32, 125, 96, 125]
    longbottom = [32, 126, 96, 126]
    downarrow = (longtop, shortbottom)
    uparrow = (shorttop, longbottom)

    def __init__(
        self,
        text: str,
        draw,
        color,
        colors,
        font=fonts.base,
        width=fonts.base_width,
        available_lines=3,
    ):
        super().__init__(text, draw, color, font, width)
        self.nr_lines = 0
        self.colors = colors
        self.start_line = 0
        self.available_lines = available_lines
        self.scrolled = False
        self.pointer = 0
        self.updated = True

    def next(self):
        if self.nr_lines <= self.available_lines:
            return
        self.pointer = (self.pointer + 1) % (self.nr_lines - self.available_lines + 1)
        self.scrolled = True
        self.updated = True

    def set_text(self, text):
        super().set_text(text)
        self.pointer = 0
        self.nr_lines = len(text)

    def draw_arrow(self, down):
        if self.nr_lines > self.available_lines:
            if down:
                self._draw_arrow(*self.downarrow)
            else:
                self._draw_arrow(*self.uparrow)

    def _draw_arrow(self, top, bottom):
        self.drawobj.rectangle([0, 126, 128, 128], fill=self.colors.get(0))
        self.drawobj.rectangle(top, fill=self.colors.get(128))
        self.drawobj.rectangle(bottom, fill=self.colors.get(128))

    def layout(self, pos: Tuple[int, int] = (0, 0)):
        if self.updated:
            self.object_text = textwrap.wrap(self.text, width=self.width)
            self.orig_object_text = self.object_text
            self.object_text = self.object_text[0 : self.available_lines]
            self.nr_lines = len(self.orig_object_text)
        if self.scrolled:
            self.object_text = self.orig_object_text[
                self.pointer : self.pointer + self.available_lines
            ]
        up = self.pointer + self.available_lines == self.nr_lines
        self.draw_arrow(not up)
        self.updated = False
        self.scrolled = False
