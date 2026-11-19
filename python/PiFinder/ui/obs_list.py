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

    def _draw_item_text(self, pos, text, row, is_focus):
        """Scroll the selected item when it is too long for the line.

        UITextMenu draws everything else: the rows, the selection box and the
        other items.
        """
        if not is_focus:
            super()._draw_item_text(pos, text, row, is_focus)
            return
        if self._scroll_item != text:
            self._scroll_item = text
            self._scroll_text = TextLayouterScroll(
                text=text,
                draw=self.draw,
                color=self.colors.get(row.brightness),
                font=row.font,
                scrollspeed=self._get_scrollspeed(),
            )
        self._scroll_text.draw(pos)

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
