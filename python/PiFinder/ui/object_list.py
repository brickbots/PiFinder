#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""

import numpy as np
import copy
from dataclasses import dataclass
from enum import Enum
from typing import Union, Optional, Tuple
from pathlib import Path
import os
import functools
from functools import cache
import re
import time

from PIL import Image, ImageChops
from itertools import cycle

from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.obj_types import OBJ_TYPE_MARKERS
from PiFinder.ui.text_menu import UITextMenu
from PiFinder.ui.base import CurrentSnapshot
from PiFinder.ui.layout import list_layout
from PiFinder.ui.object_details import UIObjectDetails

from PiFinder.calc_utils import aim_degrees, pointing_snapshot
from PiFinder import utils
from PiFinder.composite_object import CompositeObject, MagnitudeObject
from PiFinder.nearby import Nearby
from PiFinder.object_sequence import ObjectSequence
from PiFinder.catalogs import (
    CatalogState,
    ObjectLabel,
    default_display_mode_for,
    default_sort_for,
)
from PiFinder.designations import parse_designation
from PiFinder.satellite_groups import GROUPS_BY_NAME
from PiFinder.ui.sat_groups import wait_message
from PiFinder.ui.ui_utils import (
    TextLayouterScroll,
    draw_text_cached,
    name_deduplicate,
    normalize,
    pointing_arrows,
)
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


# The config option that holds the chosen left column label of each catalog,
# for example {"SA": "norad"}.
LABEL_CONFIG_OPTION = "object_list_label"

# The catalogs whose downloaded data the user can refresh from the list.
REFRESH_CATALOGS = ("CM", "MP", "SA")

# The marking menu slots of the "ID" submenu, in the order of the labels.
LABEL_SLOTS = ("left", "up", "right", "down")


class DisplayModes(Enum):
    """
    Enum for the different modes
    """

    LOCATE = 0  # shows distance to the target
    NAME = 1  # shows common names of the target
    INFO = 2  # shows magnitude, size, seen, ...


class SortOrder(Enum):
    """
    Enum for the different sort orders
    """

    CATALOG_SEQUENCE = 0  # By catalog/sequence
    NEAREST = 1  # By Distance to target
    BRIGHTEST = 2  # By apparent magnitude
    RA = 3  # By RA
    EARTH_DISTANCE = 4  # By physical distance from Earth
    OPPOSITION = 5  # By next opposition / greatest elongation
    # Satellites above the horizon first, the highest at the top. Then by
    # the start of the next visible pass.
    NEXT_PASS = 6


def _sort_objects(objects: ObjectSequence, order: SortOrder) -> ObjectSequence:
    """
    ``objects`` in ``order`` (a stable sort, so ties keep their order). Works
    on columns, so no object is made; an object without a distance or an
    opposition date sorts last.
    """
    column = {
        SortOrder.RA: "ra",
        SortOrder.BRIGHTEST: "filter_mag",
        SortOrder.EARTH_DISTANCE: "earth_distance_au",
        SortOrder.OPPOSITION: "opposition_ordinal",
        SortOrder.NEXT_PASS: "next_pass_ts",
    }.get(order)
    if column is None:
        return objects
    return objects.take(np.argsort(objects.column(column), kind="stable"))


# Sentinel for "the Nearby spatial index has never been built". A plain None
# can't serve: it is a legitimate dirty_time when no filter is configured.
_NEARBY_INDEX_UNBUILT = object()


# PiFinder's own WDS listing ("WDS 4631") and the WDS coordinate designation
# ("WDS J00568+3830"). parse_designation reads neither: "wds" is not a
# catalog code alias.
_WDS_LISTING_RE = re.compile(r"wds\s*\d+", re.IGNORECASE)
_WDS_COORDINATE_RE = re.compile(r"wds\s*j", re.IGNORECASE)


def _name_group(name: str) -> int:
    """
    Where a name goes in the NAME-mode text: 0 for a real name ("Mu And",
    "h 1057", "HD 208526"), 1 for a PiFinder catalog designation ("SaM 25",
    "M15", "WDS 4631"), 2 for a WDS coordinate designation.
    """
    name = name.strip()
    if _WDS_COORDINATE_RE.match(name):
        return 2
    if _WDS_LISTING_RE.fullmatch(name) or parse_designation(name) is not None:
        return 1
    return 0


def _sort_order_label(sort_order: "SortOrder") -> str:
    return {
        SortOrder.CATALOG_SEQUENCE: _("Catalog"),
        SortOrder.NEAREST: _("Nearby"),
        SortOrder.BRIGHTEST: _("Brightest"),
        SortOrder.RA: _("RA"),
        SortOrder.EARTH_DISTANCE: _("Distance"),
        SortOrder.OPPOSITION: _("Opposition"),
        SortOrder.NEXT_PASS: _("Next pass"),
    }[sort_order]


def _next_target_index(
    new_order,
    old_order,
    old_index: int,
) -> int:
    """
    Where the cursor lands after a list rebuild: on the previously
    selected object if it survived, else on the first of its old
    successors that did (the natural next target once the selection was
    logged or dropped below the altitude filter), clamped as a last
    resort.

    Matches listings by (catalog_code, sequence) — CompositeObject.__eq__
    compares object_id alone, which would land on a *sibling* listing
    (M 31 == NGC 224). Works on the listing-key columns, so no object is
    made.
    """
    if not len(new_order) or not len(old_order):
        return 0
    new_keys = ObjectSequence.of(new_order).column("listing_key")
    old_keys = ObjectSequence.of(old_order).column("listing_key")[max(old_index, 0) :]
    survived = np.flatnonzero(np.isin(old_keys, new_keys))
    if len(survived):
        key = old_keys[survived[0]]
        return int(np.flatnonzero(new_keys == key)[0])
    return min(max(old_index, 0), len(new_order) - 1)


# The space of the right column, in characters of the base font. The left
# label is cut to the rest of the row when the right column shows.
RIGHT_COLUMN_RESERVE_CHARS = 9

# The separator of the names in the NAME-mode text.
NAME_SEPARATOR = ", "


def right_column_text(label: str, text: str) -> str:
    """
    The text of the right column that adds information to the left label.

    The names of ``text`` that repeat the label (case, spaces and dashes are
    ignored) are removed. The function returns "" when the text is empty or
    only repeats the label. Otherwise it returns ``text`` unchanged, or the
    names that are left.
    """
    if not text.strip():
        return ""
    names = text.split(NAME_SEPARATOR)
    label_key = normalize(label.strip())
    other = [name for name in names if normalize(name.strip()) != label_key]
    if len(other) == len(names):
        return text
    return NAME_SEPARATOR.join(other)


def cut_text(text: str, chars: int) -> str:
    """``text`` cut to ``chars`` characters, the last one an ellipsis."""
    if len(text) <= chars:
        return text
    return text[: chars - 1] + "…"


@dataclass(frozen=True)
class RowText:
    """The two columns of one row of the object list.

    ``label_x`` is the start of the left column. ``label_chars`` is its
    space in characters of the row font. ``label_cut`` is True when the
    label is longer than that space.
    ``text`` is the right column text, "" when the right column is not drawn.
    ``text_x`` and ``text_chars`` give the start and the space of the right
    column.
    """

    label: str
    label_x: int
    label_chars: int
    label_cut: bool
    text: str
    text_x: int
    text_chars: int


def _error_text(data: dict) -> str:
    """The text of a catalog in the ERROR state, from its status data.

    A satellite catalog gives a reason, see SatelliteCatalog.get_status.
    """
    reason = data.get("reason")
    if reason == "no_groups":
        return _("No groups") + "\n" + _("selected")
    if reason == "failed":
        names = [
            GROUPS_BY_NAME[group].menu_label if group in GROUPS_BY_NAME else group
            for group in data.get("groups", ())
        ]
        if len(names) > 2:
            names = names[:1] + [_("and {count} more").format(count=len(names) - 1)]
        return "\n".join([_("Download failed")] + names)
    if reason == "no_data":
        return _("No data yet")
    if reason == "too_old":
        return _("Sets too old")
    return _("Error")


class UIObjectList(UITextMenu):
    """
    Displayes a list of objects
    """

    __help_name__ = "object_list"
    __title__ = "OBJECTS"
    checkmark = "󰄵"
    checkmark_no = ""
    sun = "󰖨"
    bulb = "󰛨"
    star = ""
    ruler = ""
    # The label of the left column; None shows the designation.
    current_label: Optional[ObjectLabel] = None
    # The texts and widths the scrolling texts of the focus row were made for.
    _label_scroll_key: Any = None
    _text_scroll_key: Any = None

    def __init__(self, *args, **kwargs) -> None:
        # hack at our item definition here to allow re-use of UITextMenu
        item_definition = copy.copy(kwargs["item_definition"])
        item_definition["select"] = "single"
        item_definition["items"] = []
        kwargs["item_definition"] = item_definition

        super().__init__(*args, **kwargs)
        self.screen_direction = self.config_object.get_option("screen_direction")
        self.mount_type = self.config_object.get_option("mount_type")

        self._menu_items: ObjectSequence = ObjectSequence()
        self._menu_items_sorted: ObjectSequence = ObjectSequence()
        self.catalog_info_1: str = ""
        self.catalog_info_2: str = ""
        self.catalog_data_label: str = ""
        # Filter dirty_time the Nearby spatial index was last built against
        self._nearby_index_key: Any = _NEARBY_INDEX_UNBUILT
        # Filter dirty_time the object list was last built against
        self._list_dirty_time: Any = _NEARBY_INDEX_UNBUILT

        # Init display mode defaults
        self._init_display_mode()

        # The labels of the left column, and the one that shows
        self._init_labels()

        # The sort order the list opens in. The user's choice in the marking
        # menu replaces it for the life of this list.
        self.current_sort = self._default_sort()

        marker_path = Path(utils.pifinder_dir, "markers")
        self.markers = {}
        render_size = (11, 11)
        for filename in os.listdir(marker_path):
            if filename.startswith("mrk_"):
                marker_code = filename[4:-4]
                _image = Image.new("RGB", render_size)
                _image.paste(
                    Image.open(f"{marker_path}/mrk_{marker_code}.png"),
                    (0, 0),
                )
                self.markers[marker_code] = ImageChops.multiply(
                    _image, Image.new("RGB", render_size, self.colors.get(255))
                )

        self.jump_to_number = CatalogSequence()
        self.jump_input_display = False
        self.ScrollTextLayout = functools.partial(
            TextLayouterScroll, draw=self.draw, color=self.colors.get(255)
        )
        self.last_item_index = -1
        self.item_text_scroll: Union[None, TextLayouterScroll] = None
        self.item_label_scroll: Union[None, TextLayouterScroll] = None

        # Base marking menu
        marking_menu_down = self._marking_menu_down()

        asteroid_list = self.item_definition.get("value") == "MP"
        satellite_list = self.item_definition.get("value") == "SA"
        if asteroid_list:
            third_sort = (_("OPP"), SortOrder.OPPOSITION)
        elif satellite_list:
            third_sort = (_("PASS"), SortOrder.NEXT_PASS)
        else:
            third_sort = (_("RA"), SortOrder.RA)

        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(
                label=_("Sort"),
                callback=MarkingMenu(
                    up=MarkingMenuOption(
                        label=_("MAG"),
                        callback=self.mm_change_sort,
                        value=SortOrder.BRIGHTEST,
                    ),
                    left=MarkingMenuOption(
                        label=_("NEAR"),
                        callback=self.mm_change_sort,
                        value=SortOrder.NEAREST,
                    ),
                    down=MarkingMenuOption(
                        label=third_sort[0],
                        callback=self.mm_change_sort,
                        value=third_sort[1],
                    ),
                    right=MarkingMenuOption(
                        label=_("STD"),
                        callback=self.mm_change_sort,
                        value=SortOrder.CATALOG_SEQUENCE,
                    ),
                ),
            ),
            down=marking_menu_down,
            right=MarkingMenuOption(label=_("Filter"), menu_jump="filter_options"),
        )

        if self.current_sort == SortOrder.CATALOG_SEQUENCE:
            self.marking_menu.left.callback.right.selected = True
        if self.current_sort == SortOrder.NEAREST:
            self.marking_menu.left.callback.left.selected = True
        if self.current_sort == third_sort[1]:
            self.marking_menu.left.callback.down.selected = True

        # Update object list populates self._menu_items
        # Force update because this is the first time and we
        # need to get the object list always
        self.refresh_object_list(force_update=True)
        self.nearby = Nearby(CurrentSnapshot())

    def _init_display_mode(self) -> None:
        """
        Start in the default display mode of the list's catalog: NAME for
        catalogs whose objects go by name (planets, stars, doubles), INFO for
        satellites, LOCATE for the others and for lists that mix catalogs.
        The cycle is advanced
        to that mode, so SQUARE goes on to the next mode in the usual order.
        """
        start_mode = DisplayModes.LOCATE
        if self.item_definition.get("objects") == "catalog":
            catalog_code = self.item_definition.get("value", "")
            catalog = self.catalogs.get_catalog_by_code(catalog_code)
            start_mode = DisplayModes[
                catalog.default_display_mode
                if catalog is not None
                else default_display_mode_for(catalog_code)
            ]

        self.mode_cycle = cycle(DisplayModes)
        self.current_mode = next(self.mode_cycle)
        while self.current_mode != start_mode:
            self.current_mode = next(self.mode_cycle)

    def _default_sort(self) -> SortOrder:
        """
        The sort order of the list's catalog (Catalog.default_sort), or the
        first sort order. Lists that mix catalogs get the first sort order.
        """
        if self.item_definition.get("objects") != "catalog":
            return SortOrder.CATALOG_SEQUENCE
        catalog_code = self.item_definition.get("value", "")
        catalog = self.catalogs.get_catalog_by_code(catalog_code)
        name = (
            catalog.default_sort
            if catalog is not None
            else default_sort_for(catalog_code)
        )
        return SortOrder[name] if name is not None else SortOrder.CATALOG_SEQUENCE

    def _init_labels(self) -> None:
        """
        Read the labels of the list's catalog and the stored choice. A list
        of one catalog with labels shows the stored label, or the first
        label. Other lists show the designation.
        """
        self.label_options: list[ObjectLabel] = []
        self.current_label = None
        if self.item_definition.get("objects") != "catalog":
            return
        catalog = self.catalogs.get_catalog_by_code(
            self.item_definition.get("value", "")
        )
        if catalog is None:
            return
        self.label_options = list(catalog.label_options())
        if not self.label_options:
            return
        stored = self._stored_labels().get(catalog.catalog_code)
        self.current_label = next(
            (label for label in self.label_options if label.key == stored),
            self.label_options[0],
        )

    def _marking_menu_down(self) -> MarkingMenuOption:
        """
        The DOWN slot of the marking menu. A catalog with more than one
        label gets "ID". Otherwise a downloaded dynamic catalog gets
        "Refresh": it refreshes without discarding the objects on the screen.
        """
        if len(self.label_options) > 1:
            return MarkingMenuOption(
                label=_("ID"),
                callback=self._label_marking_menu(),
            )
        if (
            self.item_definition.get("objects") == "catalog"
            and self.item_definition.get("value") in REFRESH_CATALOGS
        ):
            return MarkingMenuOption(
                label=_("Refresh"),
                callback=self.mm_refresh_dynamic_catalog,
            )
        return MarkingMenuOption()

    def _stored_labels(self) -> dict:
        """The stored label key of each catalog code."""
        stored = self.config_object.get_option(LABEL_CONFIG_OPTION, {})
        return dict(stored) if isinstance(stored, dict) else {}

    def _label_marking_menu(self) -> MarkingMenu:
        """The "ID" submenu: one slot for each label, at most four."""
        options = {slot: MarkingMenuOption() for slot in LABEL_SLOTS}
        for slot, label in zip(LABEL_SLOTS, self.label_options):
            options[slot] = MarkingMenuOption(
                label=_(label.menu_name),
                callback=self.mm_change_label,
                value=label.key,
                selected=label is self.current_label,
            )
        return MarkingMenu(**options)

    def mm_change_label(self, marking_menu, menu_item) -> bool:
        """
        Called from the "ID" submenu: show the chosen label in the left
        column, and store it for the catalog of the list.
        """
        label = next(
            (item for item in self.label_options if item.key == menu_item.value),
            None,
        )
        if label is None:
            return False
        marking_menu.select_none()
        menu_item.selected = True
        self.current_label = label
        stored = self._stored_labels()
        stored[self.item_definition["value"]] = label.key
        self.config_object.set_option(LABEL_CONFIG_OPTION, stored)
        self.refresh()
        return True

    def refresh_object_list(self, force_update=False):
        """
        Called whenever the object list might need to be updated.
        Updated here means reloaded from filtered catalog sources
        where possible

        force_update ignores filter dirty flag
        """
        catalog_filter = self.catalogs.catalog_filter
        if (
            not force_update
            and not catalog_filter.is_dirty()
            and catalog_filter.dirty_time == self._list_dirty_time
        ):
            return

        # sort() resets the cursor to the top; keep it on the selected
        # object (or its old successor) across the rebuild instead.
        old_order = self._menu_items_sorted
        old_index = self._current_item_index

        # Filter only the catalogs this list shows: a large catalog (WDS has
        # over 130,000 objects) must not slow down opening a small one.
        self.catalogs.filter_catalogs(self._source_catalogs())
        # Recorded before sort(), whose update() must see the list as current.
        self._list_dirty_time = catalog_filter.dirty_time

        # The object list can display objects from various sources
        # This key of the item definition controls where to get the
        # particular object list
        if self.item_definition["objects"] == "catalogs.filtered":
            self._menu_items = self.catalogs.get_objects(
                only_selected=True, filtered=True
            )

        if self.item_definition["objects"] == "catalog":
            for catalog in self._source_catalogs():
                self._menu_items = catalog.as_sequence(filtered=True)
                self.catalog_data_label = catalog.get_data_label() or ""
                if self.catalog_data_label:
                    self.catalog_info_2 = ""
                else:
                    age = catalog.get_age()
                    self.catalog_info_2 = "" if age is None else str(round(age, 0))

        if self.item_definition["objects"] == "recent":
            self._menu_items = ObjectSequence.of(self.ui_state.recent_list())

        if self.item_definition["objects"] == "custom":
            # item_definition must contain a list of CompositeObjects
            object_list = self.item_definition["object_list"]
            # Opt-in filtering: observing lists honour the active filter
            # (altitude, magnitude, etc); ad-hoc lists like name-search
            # results are shown as-is.
            if self.item_definition.get("filtered", False):
                object_list = self.catalogs.catalog_filter.apply(object_list)
            self._menu_items = ObjectSequence.of(object_list)

        # The header count describes the catalog behind the screen, so it is
        # deliberately the whole filtered set -- not the possibly-shorter list
        # the carousel is currently navigating (see get_nr_of_menu_items).
        self.catalog_info_1 = str(len(self._menu_items))
        self._menu_items_sorted = self._menu_items
        # _menu_items was rebuilt from source, so the spatial index no longer
        # describes it whatever the filter's dirty_time says.
        self._nearby_index_key = _NEARBY_INDEX_UNBUILT
        self.sort()
        self._current_item_index = _next_target_index(
            self._menu_items_sorted, old_order, old_index
        )

    def _sources_replaced(self) -> bool:
        """True when a catalog this list shows changed its objects (a comet,
        asteroid or satellite update) and was not filtered since."""
        return any(
            catalog.catalog_filter is not None and catalog.last_filtered == 0
            for catalog in self._source_catalogs()
        )

    def _source_catalogs(self) -> list:
        """The catalogs whose filtered objects this list shows."""
        source = self.item_definition["objects"]
        if source == "catalogs.filtered":
            return self.catalogs.get_catalogs(only_selected=True)
        if source == "catalog":
            return [
                catalog
                for catalog in self.catalogs.get_catalogs(only_selected=False)
                if catalog.catalog_code == self.item_definition["value"]
            ]
        return []

    def get_nr_of_menu_items(self):
        """Count the sorted rows that this screen actually navigates."""
        return len(self._menu_items_sorted)

    def _get_catalog_status(self):
        if self.item_definition.get("objects") != "catalog":
            return None
        catalog = self.catalogs.get_catalog_by_code(self.item_definition.get("value"))
        if catalog is None:
            return None
        status = catalog.get_status()
        if (
            status.previous != CatalogState.READY
            and status.current == CatalogState.READY
        ):
            self.refresh_object_list(force_update=True)
        return status

    def _get_catalog_status_message(
        self, status=None
    ) -> Tuple[Optional[str], Optional[int]]:
        """
        Generate status message explaining why catalog might be empty.
        Returns tuple of (message, progress_percentage). The message can
        have more than one line.
        Returns (None, None) if catalog is ready (empty is due to filtering).

        Also handles refreshing object list when catalog transitions to READY.
        """
        status = status or self._get_catalog_status()
        if status is None:
            return (None, None)
        data = status.data or {}
        progress = data.get("progress")
        if status.current == CatalogState.READY:
            return (None, None)
        if status.current == CatalogState.DOWNLOADING:
            return (_("Downloading..."), progress)
        if status.current == CatalogState.NO_GPS:
            return (_("No GPS lock"), None)
        if status.current == CatalogState.CALCULATING:
            return (_("Calculating..."), progress)
        if status.current == CatalogState.ERROR:
            return (_error_text(data), None)
        return (_("Loading..."), None)

    def _no_match_lines(self, status) -> list[str]:
        """The text of a list that the filter made empty. A catalog that
        gives its number of objects gets that number."""
        total = (status.data or {}).get("total") if status is not None else None
        if not total:
            return [
                _("No objects"),  # TRANSLATORS: no objects in object list (1/2)
                _("match filter"),  # TRANSLATORS: no objects in object list (2/2)
            ]
        if self.item_definition.get("value") == "SA":
            first = _("{count} satellites").format(count=total)
        else:
            first = _("{count} objects").format(count=total)
        return [first, _("none match"), _("the filter")]

    def _draw_empty_lines(self, begin_x: int, lines: list[str]) -> None:
        """Draw the text of an empty list from line 2, one line each."""
        for number, line in enumerate(lines):
            self.draw.text(
                (begin_x, self.line_position(2 + number)),
                line,
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
        self.screen_update()

    def sort(self, announce: bool = False) -> None:
        """
        Sorts the list by ``current_sort``. With ``announce`` (the user chose
        a sort order), a popup names the order first. A list that opens or
        refreshes shows no popup: the popup would cover the menu slide.
        """
        if announce:
            message = _("Sorting by\n{sort_order}").format(
                sort_order=_sort_order_label(self.current_sort)
            )
            self.message(message, 0.1)
            self.update()

        if self.current_sort == SortOrder.NEAREST:
            if not self.snapshot.solution().has_pointing():
                self.message(_("No Solve Yet"), 1)
                self.current_sort = SortOrder.CATALOG_SEQUENCE
            else:
                if self.catalogs.catalog_filter:
                    self._menu_items = self.catalogs.catalog_filter.apply(
                        self._menu_items
                    )
                self._build_nearby_index()
                self.nearby_refresh()
                self._current_item_index = 0

        if self.current_sort != SortOrder.NEAREST:
            self._menu_items_sorted = _sort_objects(self._menu_items, self.current_sort)
            self._current_item_index = 0
        self.update()

    def _build_nearby_index(self) -> None:
        """
        (Re)build the Nearby spatial index, skipping the rebuild while both the
        item list and the filter are unchanged -- the same dirty_time guard
        UIChart uses for its nearby-marker index.
        """
        catalog_filter = getattr(self.catalogs, "catalog_filter", None)
        dirty_time = getattr(catalog_filter, "dirty_time", None)
        if (
            self._nearby_index_key is not _NEARBY_INDEX_UNBUILT
            and self._nearby_index_key == dirty_time
        ):
            return
        self.nearby.set_items(self._menu_items)
        self._nearby_index_key = dirty_time

    def nearby_refresh(self):
        if not self.nearby.has_pointing():
            self._menu_items_sorted = self._menu_items
            self.message(_("No Solve Yet"), 1)
            return
        self._menu_items_sorted = self.nearby.refresh()

    def format_az_alt(self, point_az, point_alt):
        az_arrow_symbol, point_az, alt_arrow_symbol, point_alt = pointing_arrows(
            self, point_az, point_alt, self.mount_type
        )

        if point_az > 100:
            point_az = 99

        if point_az < 10:
            az_string = f"{az_arrow_symbol}{point_az:03.1f}"
        else:
            az_string = f"{az_arrow_symbol}{point_az:03.0f}"

        if point_alt < 10:
            alt_string = f"{alt_arrow_symbol}{point_alt:03.1f}"
        else:
            alt_string = f"{alt_arrow_symbol}{point_alt:03.0f}"

        return az_string, alt_string

    def _interpolate_color(self, mag, min_mag=9, max_mag=16):
        """
        choose a color corresponding to the Magnitude
        """
        if mag <= min_mag:
            return 255
        elif mag >= max_mag:
            return 125
        else:
            return int(255 + ((125 - 255) / (16 - 9)) * (mag - 9))

    def create_name_text(self, obj: CompositeObject) -> str:
        """
        The NAME-mode text: real names first, then PiFinder catalog
        designations, then WDS coordinate designations. The names table
        often puts designations first ("SaM 25, Mu And" on SaM 26); the
        observer looks for the name. The order inside each group is kept, and
        the row's own designation is left out.
        """
        dedups = name_deduplicate(obj.names, [f"{obj.catalog_code}{obj.sequence}"])
        # sorted() is stable, so each group keeps the names table's order.
        return ", ".join(sorted(dedups, key=_name_group))

    def create_label_text(self, obj: CompositeObject) -> str:
        """The text of the left column: the chosen label of the catalog, or
        the designation."""
        if self.current_label is not None:
            return self.current_label.text(obj)
        return self.create_shortname_text(obj)

    # Use 3-letter abbreviations for planets instead of PL1, PL2, etc.
    # Falls back to full name if planet is not in the dictionary.
    def create_shortname_text(self, obj: CompositeObject) -> str:
        if obj.catalog_code == "PL" and obj.names:
            planet_abbrevs = {
                "Mercury": "MER",
                "Venus": "VEN",
                "Moon": "MON",
                "Mars": "MAR",
                "Jupiter": "JUP",
                "Saturn": "SAT",
                "Uranus": "URA",
                "Neptune": "NEP",
                "Pluto": "PLU",
            }
            return planet_abbrevs.get(obj.names[0], obj.names[0])
        # Observing-list coordinate objects have no catalog designation; show
        # their name (e.g. "VY Andromedae") instead of "OBS1". Length is capped
        # to fit the row in update() (which knows the per-row font + screen size).
        if obj.catalog_code == "OBS" and obj.names:
            return obj.names[0]
        return f"{obj.catalog_code}{obj.sequence}"

    def create_locate_text(self, obj: CompositeObject, snapshot=None) -> str:
        az, alt = aim_degrees(
            self.snapshot,
            self.mount_type,
            self.screen_direction,
            obj,
            snapshot=snapshot,
        )
        if az:
            az_txt, alt_txt = self.format_az_alt(az, alt)
            distance = f"{az_txt} {alt_txt}"
        else:
            distance = "--- ---"
            # distance = obj.names[0] if obj.names else "--- ---"

        return distance

    def create_aka_text(self, obj: CompositeObject) -> str:
        full_name = f"{','.join(obj.names)}" if obj.names else ""
        return full_name

    def create_info_text(self, obj: CompositeObject, catalog=None) -> str:
        """
        The INFO-mode text. The catalog of the object gives it when its
        list_info_text gives a value. Else the magnitude, the size and a
        check mark when the object is logged.
        """
        if catalog is not None:
            text = catalog.list_info_text(obj)
            if text is not None:
                return text
        obj_mag = self._safe_obj_mag(obj)
        mag = f"m{obj_mag:2.0f}" if obj_mag != MagnitudeObject.UNKNOWN_MAG else "m--"
        size_str = str(obj.size)
        size = f"{self.ruler}{size_str}" if size_str else ""
        check = f" {self.checkmark}" if obj.logged else ""
        size_logged = f"{mag} {size}{check}"
        if len(size_logged) > 12:
            size_logged = f"{mag}{check}"
        return size_logged

    def _safe_obj_mag(self, obj: CompositeObject) -> float:
        """
        Extract the magnitude safely from the object
        """
        return obj.mag.filter_mag

    def _obj_to_mag_color(self, obj: CompositeObject) -> int:
        """
        Extract the magnitude safely from the object and convert it to a color
        """
        return self._interpolate_color(self._safe_obj_mag(obj))

    def _get_scrollspeed_config(self):
        scroll_dict = {
            "Off": 0,
            "Fast": TextLayouterScroll.FAST,
            "Med": TextLayouterScroll.MEDIUM,
            "Slow": TextLayouterScroll.SLOW,
        }
        scrollspeed = self.config_object.get_option("text_scroll_speed", "Med")
        return scroll_dict[scrollspeed]

    def _draw_scrollbar(self):
        # Draw scrollbar
        sbr_x = self.display.width
        sbr_y_start = self.display_class.titlebar_height + 1
        sbr_y = self.display.height
        total = self.get_nr_of_menu_items()
        if total <= 0:
            # Nothing to scroll through; a bar would divide by zero anyway.
            return
        one_item_height = max(1, int((sbr_y - sbr_y_start) / total))
        box_pos = (sbr_y - sbr_y_start) * (self._current_item_index) / (total)
        # print(f"{sbr_x=} {sbr_y=} {total=} {box_pos=} {one_item_height=}, {sbr_y_start=}, {self._current_item_index=}, {self.get_nr_of_menu_items()=}")

        self.draw.rectangle(
            (sbr_x - 1, sbr_y_start, sbr_x, sbr_y), fill=self.colors.get(128)
        )
        self.draw.rectangle(
            (
                sbr_x - 1,
                sbr_y_start + box_pos - one_item_height // 2,
                sbr_x,
                sbr_y_start + box_pos + one_item_height // 2,
            ),
            fill=self.colors.get(255),
        )

    def get_line_font_color_pos(
        self,
        line_number,
        menu_item,
        is_focus=False,
        sort_order: SortOrder = SortOrder.CATALOG_SEQUENCE,
    ):
        obj_mag_color = self._obj_to_mag_color(menu_item)

        line_font = self.fonts.base
        line_color = int(self.color_modifier(line_number, sort_order) * obj_mag_color)
        line_pos = self.line_position(line_number)

        if is_focus:
            line_color = obj_mag_color
            line_font = self.fonts.bold
        return line_font, line_color, line_pos

    @cache
    def color_modifier(self, line_number: int, sort_order: SortOrder):
        # Brightness falloff per row, generated for however many rows the
        # display shows (menu_visible_items). Reproduces the legacy 7-row
        # curves exactly and extends them for the taller 176 panel.
        n = self.display_class.menu_visible_items
        center = n // 2
        if sort_order == SortOrder.NEAREST:
            # symmetric fisheye falloff, brightest at the focus (centre) line
            by_distance = [0.8, 0.75, 0.5, 0.38, 0.3]
            return by_distance[min(abs(line_number - center), len(by_distance) - 1)]
        # CATALOG_SEQUENCE / RA: brightest at the top, descending
        descending = [1, 0.75, 0.75, 0.5, 0.5, 0.38, 0.38, 0.3, 0.3]
        return descending[min(line_number, len(descending) - 1)]

    @cache
    def line_position(self, line_number, title_offset=20):
        # Row y-positions derive from the display resolution, title-bar height
        # and font metrics (see ui.layout.list_layout). title_offset is kept for
        # call-site compatibility but the anchor now comes from the layout.
        return list_layout(self.display_class).rows[line_number].y

    def _touch_sources(self) -> None:
        """Tell the catalogs of this list that the list shows them. The
        satellite catalog updates its positions only while it is in use."""
        for catalog in self._source_catalogs():
            catalog.touch()

    def active(self):
        self._touch_sources()
        # trigger refilter
        super().active()

        # check for new push_to
        if self.ui_state.new_pushto():
            self.refresh_object_list(force_update=True)
            self.ui_state.set_new_pushto(False)
            self.show_object_details(0)
        else:
            self.refresh_object_list()

    def _draw_download_progress(self, progress: Optional[int], intensity: int) -> None:
        """Draw a compact determinate/indeterminate bar beside catalog age."""
        width = max(18, min(36, self.display.width // 4))
        height = 4
        x = self.display.width - width - 2
        y = self.line_position(0) + self.fonts.bold.height - height
        color = self.colors.get(intensity)
        self.draw.rectangle((x, y, x + width, y + height), outline=color)
        inner_width = width - 2
        if progress is None:
            segment = max(3, inner_width // 4)
            offset = int(time.monotonic() * 8) % max(1, inner_width - segment + 1)
            self.draw.rectangle(
                (x + 1 + offset, y + 1, x + offset + segment, y + height - 1),
                fill=color,
            )
        else:
            filled = round(inner_width * max(0, min(100, progress)) / 100)
            if filled:
                self.draw.rectangle(
                    (x + 1, y + 1, x + filled, y + height - 1), fill=color
                )

    def update(self, force: bool = False) -> None:
        self.clear_screen()

        # Resolution-flexible row layout: y-positions, the focus selection box
        # and text indent all derive from the display resolution, title-bar
        # height and font metrics.
        layout = list_layout(self.display_class)
        half = layout.center_index
        begin_x = layout.text_x

        # Altitude verdicts age out while the screen sits open (the sky
        # rotates); refresh the list when the filter reports staleness or a
        # dynamic catalog replaced its objects. Before the no-objects check so
        # an emptied-by-altitude list can repopulate as objects rise.
        self._touch_sources()
        catalog_filter = self.catalogs.catalog_filter
        if catalog_filter is not None and (
            catalog_filter.dirty_time != self._list_dirty_time
            or catalog_filter.is_stale()
            or self._sources_replaced()
        ):
            self.refresh_object_list(force_update=True)

        # Poll dynamic-catalog state even while objects remain populated: an
        # update keeps serving the old catalog and reports download progress.
        catalog_status = self._get_catalog_status()

        # no objects to display
        if self.get_nr_of_menu_items() == 0:
            # Get catalog-specific status message if available
            status_msg, progress = self._get_catalog_status_message(catalog_status)

            # Re-check menu items in case refresh happened during status check
            if self.get_nr_of_menu_items() > 0:
                # Objects were loaded, continue with normal rendering
                pass
            elif status_msg:
                # The status message from line 2, then the progress.
                lines = status_msg.split("\n")
                if progress is not None:
                    lines.append(f"{progress}%")
                self._draw_empty_lines(begin_x, lines)
                return
            else:
                # The catalog is ready: the filter made the list empty.
                self._draw_empty_lines(begin_x, self._no_match_lines(catalog_status))
                return

        # should we refresh the nearby list?
        if self.current_sort == SortOrder.NEAREST and self.nearby.should_refresh():
            # A pointing-driven re-rank, not a list rebuild: the user slewed in
            # order to change what is nearest, so while the cursor sits on the
            # top row it keeps following the pointing. Once they have scrolled
            # off the top they are browsing, and the cursor pins to the
            # selected object as it migrates through the ranking.
            parked_at_top = self._current_item_index == 0
            old_order = self._menu_items_sorted
            old_index = self._current_item_index
            self.nearby_refresh()
            self._current_item_index = (
                0
                if parked_at_top
                else _next_target_index(self._menu_items_sorted, old_order, old_index)
            )

        # Draw sorting mode in the empty rows above the focus line
        if self._current_item_index < half:
            intensity: int = int(64 + (((half - 1) - self._current_item_index) * 32.0))
            catalog_header = _("{catalog_info_1} obj").format(
                catalog_info_1=self.catalog_info_1
            )
            if self.catalog_data_label:
                catalog_header += f", {self.catalog_data_label}"
            elif self.catalog_info_2:
                catalog_header += _(", {catalog_info_2}d old").format(
                    catalog_info_2=self.catalog_info_2
                )
            draw_text_cached(
                self.screen,
                (begin_x, self.line_position(0)),
                catalog_header,
                self.fonts.bold.font,
                self.colors.get(intensity),
            )
            draw_text_cached(
                self.screen,
                (begin_x, self.line_position(1)),
                _("Sort: {sort_order}").format(
                    sort_order=_sort_order_label(self.current_sort)
                ),
                self.fonts.bold.font,
                self.colors.get(intensity),
            )
            if (
                catalog_status is not None
                and catalog_status.current == CatalogState.DOWNLOADING
            ):
                progress = (
                    catalog_status.data.get("progress") if catalog_status.data else None
                )
                self._draw_download_progress(progress, intensity)
        # Draw current selection hint
        self.draw.rectangle(layout.selection_box, outline=self.colors.get(128), width=1)
        line_number, line_pos = 0, 0
        line_color = None
        # One read of the pointing state for all rows of this frame.
        pointing = (
            pointing_snapshot(self.snapshot)
            if self.current_mode == DisplayModes.LOCATE
            else None
        )
        # The catalog of each catalog code of this frame's rows.
        row_catalogs: dict = {}
        for i in range(
            self._current_item_index - half, self._current_item_index + half + 1
        ):
            if i >= 0 and i < len(self._menu_items_sorted):
                _menu_item = self._menu_items_sorted[i]
                is_focus = line_number == half

                item_name = self.create_label_text(_menu_item)
                item_text = ""
                if self.current_mode == DisplayModes.LOCATE:
                    item_text = self.create_locate_text(_menu_item, pointing)
                elif self.current_mode == DisplayModes.NAME:
                    item_text = self.create_name_text(_menu_item)
                elif self.current_mode == DisplayModes.INFO:
                    item_text = self.create_info_text(
                        _menu_item, self._catalog_of(_menu_item, row_catalogs)
                    )

                # figure out line position / color / font
                line_font, line_color, line_pos = self.get_line_font_color_pos(
                    line_number, _menu_item, is_focus=is_focus
                )

                row = self.row_text(item_name, item_text, line_font, layout.text_x)

                # Type Marker
                line_bg = 32 if is_focus else 0
                marker = self.get_marker(_menu_item.obj_type, line_color, line_bg)
                if marker is not None:
                    self.screen.paste(
                        marker, (layout.marker_x, line_pos + layout.marker_dy)
                    )

                if is_focus:
                    self._draw_focus_row(row, line_font, line_color, line_pos)
                else:
                    self._draw_row(row, line_font, line_color, line_pos)

            line_number += 1

        if self.jump_input_display:
            self.message(
                str(self.jump_to_number),
                0.1,
                [30, 10, 93, 40],
            )
        self._draw_scrollbar()

        self.screen_update()

    def _catalog_of(self, obj: CompositeObject, found: dict):
        """The catalog of ``obj``, or None. ``found`` keeps the catalogs that
        this frame found."""
        code = obj.catalog_code
        if code not in found:
            found[code] = self.catalogs.get_catalog_by_code(code)
        return found[code]

    def row_text(self, label: str, text: str, font, label_x: int) -> RowText:
        """
        The space of the two columns of a row in ``font``.

        The right column shows only when its text adds information to the
        label (see right_column_text). Then the label gets the row width
        minus a reserve for the right column. Else the label gets the full
        row width. The widths come from the display width and the font, so
        they follow the 128, 176 and 320 px layouts.
        """
        text = right_column_text(label, text)
        row_px = self.display.width - label_x
        if text:
            row_px -= RIGHT_COLUMN_RESERVE_CHARS * self.fonts.base.width
        label_chars = max(3, row_px // font.width)
        label_cut = len(label) > label_chars
        shown_chars = label_chars if label_cut else len(label)
        text_x = label_x + (shown_chars + 1) * font.width
        text_chars = max(0, (self.display.width - text_x) // font.width)
        return RowText(
            label=label,
            label_x=label_x,
            label_chars=label_chars,
            label_cut=label_cut,
            text=text,
            text_x=text_x,
            text_chars=text_chars,
        )

    def _draw_row(self, row: RowText, font, color: int, line_pos: int) -> None:
        """Draw a row that is not the focus row. A long label is cut."""
        draw_text_cached(
            self.screen,
            (row.label_x, line_pos),
            cut_text(row.label, row.label_chars),
            font.font,
            self.colors.get(color),
        )
        if row.text:
            draw_text_cached(
                self.screen,
                (row.text_x, line_pos),
                row.text,
                font.font,
                self.colors.get(color),
            )

    def _update_focus_scrollers(self, row: RowText, font, color: int) -> None:
        """
        Make the scrolling texts of the focus row again when the focus moved
        or their text changed. Only one text of the row scrolls. A cut label
        scrolls in the left column, and the right column text stays still.
        Else the right column text scrolls, as before. The two texts have
        their own keys: a LOCATE text that changes in each frame does not
        start the label scroll again.
        """
        scrollspeed = self._get_scrollspeed_config()
        label_scrolls = row.label_cut and scrollspeed > 0
        if self.last_item_index != self._current_item_index:
            self.last_item_index = self._current_item_index
            self._label_scroll_key = None
            self._text_scroll_key = None

        label_key = (row.label, row.label_chars, color, scrollspeed)
        if not label_scrolls:
            self.item_label_scroll = None
            self._label_scroll_key = None
        elif label_key != self._label_scroll_key:
            self._label_scroll_key = label_key
            self.item_label_scroll = self.ScrollTextLayout(
                row.label,
                font=font,
                width=row.label_chars,
                scrollspeed=scrollspeed,
                color=self.colors.get(color),
            )

        text_key = (row.text, row.text_chars, scrollspeed)
        if label_scrolls or not row.text:
            self.item_text_scroll = None
            self._text_scroll_key = None
        elif text_key != self._text_scroll_key:
            self._text_scroll_key = text_key
            self.item_text_scroll = self.ScrollTextLayout(
                row.text,  # TODO I18N: Does this need to be translated?
                font=self.fonts.bold,
                width=row.text_chars,
                scrollspeed=scrollspeed,
            )

    def _draw_focus_row(self, row: RowText, font, color: int, line_pos: int) -> None:
        """Draw the focus row. A long label or a long right text scrolls."""
        self._update_focus_scrollers(row, font, color)
        if self.item_label_scroll is not None:
            self.item_label_scroll.draw((row.label_x, line_pos))
            if row.text:
                draw_text_cached(
                    self.screen,
                    (row.text_x, line_pos),
                    cut_text(row.text, row.text_chars),
                    font.font,
                    self.colors.get(color),
                )
            return
        draw_text_cached(
            self.screen,
            (row.label_x, line_pos),
            cut_text(row.label, row.label_chars),
            font.font,
            self.colors.get(color),
        )
        if self.item_text_scroll is not None:
            self.item_text_scroll.draw((row.text_x, line_pos))

    def scroll_to_sequence(
        self, sequence: int, start_at_top=True, direction="down"
    ) -> None:
        """
        Scrolls the list to the first item matching
        this number
        """
        if start_at_top:
            self._current_item_index = 0

        hits = np.flatnonzero(self._menu_items_sorted.column("sequence") == sequence)
        if direction == "down":
            hits = hits[hits > self._current_item_index]
        else:
            hits = hits[hits < self._current_item_index - 1][::-1]
        if len(hits):
            self._current_item_index = int(hits[0])

    def get_marker(
        self, obj_type: str, color: int, bgcolor: int
    ) -> Union[Image.Image, None]:
        """
        Returns the right marker for this object
        multiplied by the color

        returns None if no marker is found for this obj type
        """
        marker = OBJ_TYPE_MARKERS.get(obj_type)
        if marker is None:
            return None

        marker_img = self.markers[marker]

        # dim
        _img = Image.new("RGB", marker_img.size, self.colors.get(color))
        marker_img = ImageChops.multiply(marker_img, _img)

        # raise by bg
        _img = Image.new("RGB", marker_img.size, self.colors.get(bgcolor))
        marker_img = ImageChops.add(marker_img, _img)

        return marker_img

    def refresh(self):
        self.last_item_index = -1

    def key_up(self):
        if self.jump_input_display:
            self.scroll_to_sequence(
                self.jump_to_number.object_number, start_at_top=False, direction="up"
            )
        else:
            super().key_up()

    def key_down(self):
        if self.jump_input_display:
            self.scroll_to_sequence(
                self.jump_to_number.object_number, start_at_top=False, direction="down"
            )
        else:
            super().key_down()

    def cycle_display_mode(self):
        """
        Switch display modes
        """
        if self.jump_input_display:
            self.jump_input_display = False
            self.jump_to_number.reset_number()
        else:
            self.current_mode = next(self.mode_cycle)
            self.refresh()

    def show_object_details(self, object_index):
        """
        Adds the object details UI module for the object
        at object_index to the top of the stack.
        """
        _menu_item = self._menu_items_sorted[object_index]

        object_item_definition = {
            "name": _menu_item.display_name,
            "class": UIObjectDetails,
            "object": _menu_item,
            "object_list": self._menu_items_sorted,
            # The row itself: a list can hold one listing twice (an observing
            # list naming it twice), and only the index tells them apart.
            "object_index": object_index,
            "label": "object_details",
        }
        self.add_to_stack(object_item_definition)

    def key_right(self):
        """
        When right is pressed, move to
        object info screen
        """
        nr_menu_items = self.get_nr_of_menu_items()
        if nr_menu_items == 0 or self._current_item_index >= nr_menu_items:
            return

        # turn off input box if it's there
        if self.jump_input_display:
            self.jump_input_display = False
            self.jump_to_number.reset_number()

        self.show_object_details(self._current_item_index)

    def key_number(self, number):
        if not self.jump_input_display:
            # As many digits as the list's largest number: a Named Stars HIP
            # number or a WDS sequence has six.
            largest = max((obj.sequence for obj in self._menu_items_sorted), default=0)
            self.jump_to_number.width = max(4, len(str(largest)))
        self.jump_to_number.append_number(number)
        if not self.jump_to_number.has_number():
            self.jump_input_display = False
            return

        self.jump_input_display = True

        # Check for match
        self.scroll_to_sequence(self.jump_to_number.object_number)

        self.update()

    def key_long_up(self):
        self.menu_scroll(-1)

    def key_long_down(self):
        self.menu_scroll(999999999999999999999999999)

    def mm_change_sort(self, marking_menu, menu_item):
        """
        Called to change sort order from MM
        """
        marking_menu.select_none()
        menu_item.selected = True

        sort_order = getattr(menu_item, "value", None)
        if not isinstance(sort_order, SortOrder):
            return False

        self.current_sort = sort_order
        self.sort(announce=True)
        return True

    def mm_jump_to_filter(self, marking_menu, menu_item):
        pass

    def serialize_ui_state(self) -> dict:
        """
        Serialize the current state of the object list for inter-process communication
        """
        try:
            # _current_item_index addresses the sorted list, which is what the
            # screen draws -- indexing _menu_items reports a different object
            # under any sort that reorders or shortens the source.
            current_item = None
            if 0 <= self._current_item_index < len(self._menu_items_sorted):
                obj = self._menu_items_sorted[self._current_item_index]
                # For CompositeObject, use display_name which is JSON serializable
                current_item = (
                    obj.display_name if hasattr(obj, "display_name") else str(obj)
                )

            return {
                "current_index": self._current_item_index,
                "current_item": current_item,
                "total_items": len(self._menu_items_sorted),
                "display_mode": self.current_mode.name
                if hasattr(self.current_mode, "name")
                else str(self.current_mode),
                "sort_order": self.current_sort.name
                if hasattr(self.current_sort, "name")
                else str(self.current_sort),
                "catalog_info_1": self.catalog_info_1,
                "catalog_info_2": self.catalog_info_2,
                "catalog_data_label": self.catalog_data_label,
            }
        except Exception as e:
            return {"error": f"Failed to serialize object list state: {str(e)}"}

    def mm_refresh_dynamic_catalog(self, marking_menu, menu_item):
        """Refresh downloaded elements while retaining the active objects."""
        catalog = self.catalogs.get_catalog_by_code(self.item_definition.get("value"))
        if catalog and hasattr(catalog, "refresh"):
            # A catalog that refuses the refresh returns the seconds to wait.
            wait_seconds = catalog.refresh()
            if wait_seconds:
                self.message(wait_message(wait_seconds), 2)
            else:
                self.message(
                    _("Refreshing..."), 1
                )  # TRANSLATORS: Status message when refreshing comet catalog
            # Keep the current objects visible and refresh the status header.
            self.refresh_object_list(force_update=True)
        return True


class CatalogSequence:
    """
    Holds the string that represents the numeric portion
    of a catalog entry
    """

    def __init__(self):
        self.object_number = 0
        self.width = 4
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
        return self.width

    def get_designator(self):
        number_str = str(self.object_number) if self.has_number() else ""
        return f"{number_str:->{self.get_catalog_width()}}"

    def __str__(self):
        return self.field

    def __repr__(self):
        return self.field
