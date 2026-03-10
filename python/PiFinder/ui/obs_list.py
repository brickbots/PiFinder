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

        title = os.path.basename(subdir) if subdir else "Obs Lists"
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

        line_number = 0
        line_horiz_pos = 13

        for i in range(self._current_item_index - 3, self._current_item_index + 4):
            if 0 <= i < self.get_nr_of_menu_items():
                line_font = self.fonts.base
                if line_number == 0:
                    line_color = 96
                    line_pos = 0
                elif line_number == 1:
                    line_color = 128
                    line_pos = 13
                elif line_number == 2:
                    line_color = 192
                    line_font = self.fonts.bold
                    line_pos = 25
                elif line_number == 3:
                    line_color = 256
                    line_font = self.fonts.large
                    line_pos = 40
                elif line_number == 4:
                    line_color = 192
                    line_font = self.fonts.bold
                    line_pos = 60
                elif line_number == 5:
                    line_color = 128
                    line_pos = 76
                else:
                    line_color = 96
                    line_pos = 89

                line_pos += 20
                item_text = str(self._menu_items[i])

                if line_number == 3:
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

            line_number += 1

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
            self.message(f"Error loading\n{parsed} parsed", 2)
            return False

        self.ui_state.set_observing_list(catalog_objects)
        display_name = os.path.splitext(os.path.basename(list_name))[0]
        self.message(f"{display_name}\n{matched}/{parsed} objects", 2)

        object_list_def = {
            "name": display_name,
            "class": UIObjectList,
            "objects": "custom",
            "object_list": catalog_objects,
            "label": "obs_list",
        }
        self.add_to_stack(object_list_def)
        return False

    def key_left(self):
        return True
