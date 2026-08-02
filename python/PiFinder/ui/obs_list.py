"""
UI module for browsing and loading
observing lists from ~/PiFinder_data/obslists/

Supports all formats handled by obslist_formats:
SkySafari, CSV, Stellarium, Autostar, Argo Navis, NexTour, EQMOD, plain text.
"""

import os
import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


from PiFinder.ui.text_menu import UITextMenu
from PiFinder.ui.object_list import UIObjectList
from PiFinder.ui.ui_utils import TextLayouterScroll
from PiFinder import obslist

logger = logging.getLogger("UI.ObsList")


class UIObsList(UITextMenu):
    """Lists available .skylist files and folders, supports subfolder navigation."""

    __title__ = "Obs Lists"

    # The list is drawn as a 7-row window centered on the selection. Each row has
    # a fixed color, vertical offset and font; the middle row is the selected
    # item -- brightest and largest, and it scrolls when its text overflows.
    _SELECTED_ROW = 3
    _ROW_STYLES = (
        # (color, y_offset, font_name)
        (96, 0, "base"),
        (128, 13, "base"),
        (192, 25, "bold"),
        (255, 40, "large"),
        (192, 60, "bold"),
        (128, 76, "base"),
        (96, 89, "base"),
    )

    def __init__(self, *args, **kwargs):
        incoming = kwargs.get("item_definition", {})
        subdir = incoming.get("subdir", "")

        entries = obslist.get_lists(subdir)
        items = []
        for entry in entries:
            if entry["type"] == "folder":
                items.append(
                    {
                        "name": f"[{entry['name']}]",
                        "class": UIObsList,
                        "subdir": entry["subdir"],
                    }
                )
            else:
                items.append(
                    {
                        "name": entry["name"],
                        "value": entry["path"],
                    }
                )

        title = os.path.basename(subdir) if subdir else _("Obs Lists")
        kwargs["item_definition"] = {
            "name": title,
            "select": "single",
            "items": items,
        }
        super().__init__(*args, **kwargs)
        self.__title__ = title
        self._scroll_text = None
        self._scroll_item = None

    def _get_scrollspeed(self):
        scroll_dict = {
            "Fast": TextLayouterScroll.FAST,
            "Med": TextLayouterScroll.MEDIUM,
            "Slow": TextLayouterScroll.SLOW,
        }
        return scroll_dict.get(
            self.config_object.get_option("text_scroll_speed", "Med"),
            TextLayouterScroll.MEDIUM,
        )

    def update(self, force=False):
        self.clear_screen()
        self.draw.rectangle((-1, 60, 129, 80), outline=self.colors.get(128), width=1)

        line_horiz_pos = 13
        window_start = self._current_item_index - self._SELECTED_ROW

        for line_number, style in enumerate(self._ROW_STYLES):
            i = window_start + line_number
            if not (0 <= i < self.get_nr_of_menu_items()):
                continue

            line_color, line_pos, font_name = style
            line_font = getattr(self.fonts, font_name)
            line_pos += 20
            item_text = str(self._menu_items[i])

            if line_number == self._SELECTED_ROW:
                # Scroll the selected item if it's too long
                if self._scroll_item != item_text:
                    self._scroll_item = item_text
                    self._scroll_text = TextLayouterScroll(
                        text=_(item_text),
                        draw=self.draw,
                        color=self.colors.get(line_color),
                        font=line_font,
                        scrollspeed=self._get_scrollspeed(),
                    )
                self._scroll_text.draw((line_horiz_pos, line_pos))
            else:
                self.draw.text(
                    (line_horiz_pos, line_pos),
                    _(item_text),
                    font=line_font.font,
                    fill=self.colors.get(line_color),
                )

        return self.screen_update()

    def key_right(self):
        if not self._menu_items:
            return False

        selected = self._menu_items[self._current_item_index]
        item_def = self.get_item(selected)

        if item_def and item_def.get("class"):
            self.add_to_stack(item_def)
            return False

        list_name = item_def["value"]

        result = obslist.read_list(self.catalogs, list_name)
        catalog_objects = result.get("catalog_objects", [])

        parsed = result.get("objects_parsed", 0)
        matched = len(catalog_objects)

        if result["result"] != "success":
            self.message(_("Error loading\n{parsed} parsed").format(parsed=parsed), 2)
            return False

        self.ui_state.set_observing_list(catalog_objects)
        display_name = os.path.splitext(os.path.basename(list_name))[0]
        self.message(
            _("{name}\n{matched}/{parsed} objects").format(
                name=display_name, matched=matched, parsed=parsed
            ),
            2,
        )

        object_list_def = {
            "name": display_name,
            "class": UIObjectList,
            "objects": "custom",
            "object_list": catalog_objects,
            "filtered": True,
            "label": "obs_list",
        }
        self.add_to_stack(object_list_def)
        return False

    def key_left(self):
        return True
