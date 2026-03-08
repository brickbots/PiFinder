"""
UI module for browsing and loading
SkySafari observing lists (.skylist files)
from ~/PiFinder_data/obslists/
"""

import logging

from PiFinder.ui.text_menu import UITextMenu
from PiFinder.ui.object_list import UIObjectList
from PiFinder import obslist

logger = logging.getLogger("UI.ObsList")


class UIObsList(UITextMenu):
    """Lists available .skylist files and loads the selected one."""

    __title__ = "Obs Lists"

    def __init__(self, *args, **kwargs):
        lists = obslist.get_lists()
        items = [{"name": name, "value": name} for name in sorted(lists)]
        kwargs["item_definition"] = {
            "name": "Obs Lists",
            "select": "single",
            "items": items,
        }
        super().__init__(*args, **kwargs)

    def key_right(self):
        if not self._menu_items:
            return False

        selected = self._menu_items[self._current_item_index]
        item_def = self.get_item(selected)
        list_name = item_def["value"]

        result = obslist.read_list(self.catalogs, list_name)
        catalog_objects = result.get("catalog_objects", [])

        if result["result"] != "success" or not catalog_objects:
            parsed = result.get("objects_parsed", 0)
            matched = len(catalog_objects)
            self.message(f"Loaded {matched}/{parsed}\nobjects", 2)
            if not catalog_objects:
                return False

        self.ui_state.set_observing_list(catalog_objects)
        self.message(f"{list_name}\n{len(catalog_objects)} objects", 2)

        object_list_def = {
            "name": list_name,
            "class": UIObjectList,
            "objects": "custom",
            "object_list": catalog_objects,
            "label": "obs_list",
        }
        self.add_to_stack(object_list_def)
        return False

    def key_left(self):
        return True
