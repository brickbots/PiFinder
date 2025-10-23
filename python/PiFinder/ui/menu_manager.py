import time
import os
from typing import Union
from PIL import Image
from PiFinder import utils
from PiFinder.ui.base import UIModule
from PiFinder.ui import menu_structure
from PiFinder.ui.sqmentry import UISqmEntry
from PiFinder.ui.object_details import UIObjectDetails
from PiFinder.displays import DisplayBase
from PiFinder.ui.text_menu import UITextMenu
from PiFinder.ui.marking_menus import (
    MarkingMenu,
    MarkingMenuOption,
    render_marking_menu,
)
from PiFinder.ui.textentry import UITextEntry


def collect_preloads() -> list[dict]:
    """
    Returns a list of modules to preload
    """
    preload_modules = []
    stack = [menu_structure.pifinder_menu]
    while stack:
        menu_item = stack.pop()
        menu_item["foo"] = "Bar"
        for k, v in menu_item.items():
            if isinstance(v, dict):
                stack.append(v)
                break
            elif isinstance(v, list):
                stack.extend(v)
            elif k == "preload" and v is True:
                preload_modules.append(menu_item)
    return preload_modules


def find_menu_by_label(label: str):
    """
    Returns the FIRST instance of a menu dict
    with the specified key.  labels in the menu
    struct should be unique.

    Returns None is not found
    """
    stack = [menu_structure.pifinder_menu]
    while stack:
        menu_item = stack.pop()
        for k, v in menu_item.items():
            if isinstance(v, dict):
                stack.append(v)
                break
            elif isinstance(v, list):
                stack.extend(v)
            elif k == "label" and v == label:
                return menu_item
    return None


def dyn_menu_equipment(cfg):
    """
    Add's equipment related menus to the menu tree
    these are hidden under the equipment ui menu object
    """
    equipment_menu_item = find_menu_by_label("equipment")

    eyepiece_menu_items = []
    for eyepiece in cfg.equipment.eyepieces:
        eyepiece_menu_items.append(
            {
                "name": f"{eyepiece.focal_length_mm}mm {eyepiece.name}",
                "value": eyepiece,
            }
        )

    eyepiece_menu = {
        "name": _("Eyepiece"),
        "class": UITextMenu,
        "select": "single",
        "label": "select_eyepiece",
        "config_option": "equipment.active_eyepiece",
        "items": eyepiece_menu_items,
    }

    # Loop over telescopes
    telescope_menu_items = []
    for telescope in cfg.equipment.telescopes:
        telescope_menu_items.append(
            {
                "name": telescope.name,
                "value": telescope,
            }
        )

    telescope_menu = {
        "name": _("Telescope"),
        "class": UITextMenu,
        "select": "single",
        "label": "select_telescope",
        "config_option": "equipment.active_telescope",
        "items": telescope_menu_items,
    }

    equipment_menu_item["items"] = [telescope_menu, eyepiece_menu]


def dyn_menu_sqm(shared_state):
    """
    Adds a submenu to the SQM page to manually set the SQM value
    """
    sqm_menu_item = find_menu_by_label("sqm")
    sqm_menu = {
        "name": _("SQM Value"),
        "class": UISqmEntry,
        "label": "set_sqm",
    }
    sqm_menu_item["items"] = [sqm_menu]


class MenuManager:
    def __init__(
        self,
        display_class: DisplayBase,
        camera_image,
        shared_state,
        command_queues,
        config_object,
        catalogs,
    ):
        self.display_class = display_class
        self.shared_state = shared_state
        self.ui_state = shared_state.ui_state()
        self.camera_image = camera_image
        self.command_queues = command_queues
        self.config_object = config_object
        self.catalogs = catalogs

        # stack switch anim stuff
        self._stack_anim_counter: float = 0
        self._stack_anim_direction: int = 0

        self.stack: list[type[UIModule]] = []
        self.add_to_stack(menu_structure.pifinder_menu)

        self.marking_menu_stack: list[MarkingMenu] = []
        self.marking_menu_bg: Union[Image.Image, None] = None

        # This will be populated if we are in 'help' mode
        self.help_images: Union[None, list[Image.Image]] = None
        self.help_image_index = 0

        # screenshot stuff
        root_dir = str(utils.data_dir)
        self.ss_path = os.path.join(root_dir, "screenshots")
        self.ss_count = 0

        dyn_menu_equipment(self.config_object)
        dyn_menu_sqm(shared_state)
        self.preload_modules()

    def screengrab(self):
        self.ss_count += 1
        filename = f"{self.stack[-1].__uuid__}_{self.ss_count :0>3}_{self.stack[-1].title.replace('/','-')}"
        ss_imagepath = self.ss_path + f"/{filename}.png"
        ss = self.shared_state.screen().copy()
        ss.save(ss_imagepath)
        print(ss_imagepath)

    def remove_from_stack(self) -> None:
        if len(self.stack) > 1:
            self._stack_top_image = self.stack[-1].screen.copy()
            self.stack[-1].inactive()  # type: ignore[call-arg]
            self.stack.pop()
            self.stack[-1].active()  # type: ignore[call-arg]
            self._stack_anim_counter = time.time() + self.config_object.get_option(
                "menu_anim_speed", 0
            )
            self._stack_anim_direction = 1

    def preload_modules(self) -> None:
        """
        Loads any modules that need a bit of extra time
        like chart, so they are ready to go
        """
        for module_def in collect_preloads():
            module_def["state"] = module_def["class"](
                display_class=self.display_class,
                camera_image=self.camera_image,
                shared_state=self.shared_state,
                command_queues=self.command_queues,
                config_object=self.config_object,
                catalogs=self.catalogs,
                item_definition=module_def,
                add_to_stack=self.add_to_stack,
                remove_from_stack=self.remove_from_stack,
                jump_to_label=self.jump_to_label,
            )

    def add_to_stack(self, item: dict) -> None:
        """
        Adds a new module to the stack by creating
        a new instance of the specified class, passing
        in all the required UI Module arguments + the
        item dict
        """
        if item.get("state") is not None:
            self.stack[-1].inactive()  # type: ignore[call-arg]
            self.stack.append(item["state"])
        else:
            self.stack.append(
                item["class"](
                    display_class=self.display_class,
                    camera_image=self.camera_image,
                    shared_state=self.shared_state,
                    command_queues=self.command_queues,
                    config_object=self.config_object,
                    catalogs=self.catalogs,
                    item_definition=item,
                    add_to_stack=self.add_to_stack,
                    remove_from_stack=self.remove_from_stack,
                    jump_to_label=self.jump_to_label,
                )
            )
            if item.get("stateful", False):
                item["state"] = self.stack[-1]

        self.stack[-1].active()  # type: ignore[call-arg]
        if len(self.stack) > 1:
            self._stack_anim_counter = time.time() + self.config_object.get_option(
                "menu_anim_speed", 0
            )
            self._stack_anim_direction = -1

    def message(self, message: str, timeout: float) -> None:
        self.stack[-1].message(message, timeout)  # type: ignore[arg-type]

    def jump_to_label(self, label: str) -> None:
        # to prevent many recent/object UI modules
        # being added to the list upon repeated object
        # pushes, check for existing 'recent' in the
        # stack and jump to that, rather than adding
        # a new one
        if label in ["recent"]:
            for stack_index, ui_module in enumerate(self.stack):
                if ui_module.item_definition.get("label", "") == label:
                    self.stack = self.stack[: stack_index + 1]
                    self.stack[-1].active()  # type: ignore[call-arg]
                    return
        # either this is not a special case, or we didn't find
        # the label already in the stack
        menu_to_jump = find_menu_by_label(label)
        if menu_to_jump is not None:
            self.add_to_stack(menu_to_jump)

    def exit_marking_menu(self):
        """
        Do any cleanup related to exiting the marking
        menu system
        """
        self.marking_menu_bg = None
        self.marking_menu_stack = []

    def display_marking_menu(self):
        """
        Called to display the marking menu
        """
        if self.marking_menu_bg is None:
            # Grab current screen to re-use as background of
            # all marking menus
            self.marking_menu_bg = self.stack[-1].screen.copy()
        if self.marking_menu_stack != []:
            marking_menu_image = render_marking_menu(
                self.marking_menu_bg.copy(),
                self.marking_menu_stack[-1],
                self.display_class,
                39,
            )
            self.update_screen(marking_menu_image)

    def flash_marking_menu_option(self, option: MarkingMenuOption) -> None:
        assert self.marking_menu_bg is not None, ""
        marking_menu_image = render_marking_menu(
            self.marking_menu_bg.copy(),
            self.marking_menu_stack[-1],
            self.display_class,
            39,
            option,
        )
        self.update_screen(marking_menu_image)
        time.sleep(0.15)

    def update(self) -> None:
        if self.help_images is not None:
            # We are in help mode, just chill...
            return

        if self.marking_menu_stack != []:
            # We are displaying a marking menu... chill
            return

        # Business as usual, update the module at the top of the stack
        self.stack[-1].update()  # type: ignore[call-arg]

        # are we animating?
        if self._stack_anim_counter > time.time():
            if self._stack_anim_direction == 1:
                # backing out....
                top_image = self._stack_top_image
                bottom_image = self.stack[-1].screen
                top_pos = int(
                    (
                        self.display_class.resolution[0]
                        / self.config_object.get_option("menu_anim_speed", 0)
                    )
                    * (
                        self.config_object.get_option("menu_anim_speed", 0)
                        - (self._stack_anim_counter - time.time())
                    )
                )
            else:
                top_image = self.stack[-1].screen
                bottom_image = self.stack[-2].screen
                top_pos = int(
                    (
                        self.display_class.resolution[0]
                        / self.config_object.get_option("menu_anim_speed", 0)
                    )
                    * (self._stack_anim_counter - time.time())
                )
            bottom_image.paste(top_image, (top_pos, 0))

            self.update_screen(bottom_image)
        else:
            self.update_screen(self.stack[-1].screen)

    def update_screen(self, screen_image: Image.Image) -> None:
        """
        Put an image on the display
        """
        screen_to_display = screen_image.convert(self.display_class.device.mode)

        if time.time() < self.ui_state.message_timeout():
            return None

        self.display_class.device.display(screen_to_display)

        # Only update shared state when not in message timeout
        if self.shared_state:
            self.shared_state.set_screen(screen_to_display)

    def key_number(self, number):
        if self.help_images is not None:
            # Exit help
            self.help_images = None
            self.update()
            return

        self.stack[-1].key_number(number)

    def key_plus(self):
        self.stack[-1].key_plus()

    def key_minus(self):
        self.stack[-1].key_minus()

    def key_long_square(self):
        if self.help_images is not None:
            # Exit help
            self.help_images = None
            self.update()
            return

        if self.marking_menu_stack == []:
            if self.stack[-1].marking_menu is not None:
                self.marking_menu_stack.append(self.stack[-1].marking_menu)
        else:
            self.exit_marking_menu()

        if self.marking_menu_stack != []:
            self.display_marking_menu()

    def key_square(self):
        if self.help_images is not None:
            # Exit help
            self.help_images = None
            self.update()
            return

        if self.marking_menu_stack != []:
            self.marking_menu_stack.pop()
            if self.marking_menu_stack == []:
                # Make sure we clean up
                self.exit_marking_menu()
            self.update()
            return

        self.stack[-1].key_square()

    def key_long_up(self):
        pass

    def key_long_down(self):
        pass

    def key_long_right(self):
        # jump to recent objects
        if self.stack[-1].item_definition.get("label") != "object_details":
            recent_list = self.ui_state.recent_list()
            if len(recent_list) > 0:
                object_item_definition = {
                    "name": recent_list[-1].display_name,
                    "class": UIObjectDetails,
                    "object_list": recent_list,
                    "object": recent_list[-1],
                    "label": "object_details",
                }
                self.add_to_stack(object_item_definition)

    def key_long_left(self):
        """
        Return to top of menu
        """
        if self.help_images is not None:
            # Exit help
            self.help_images = None
            self.update()

        self.stack[-1].inactive()
        self.stack = self.stack[:1]
        self.stack[0].active()

    def key_left(self):
        if self.help_images is not None:
            # Exit help
            self.help_images = None
            self.update()
            return

        if self.marking_menu_stack != []:
            self.mm_select(self.marking_menu_stack[-1].left)
        else:
            # always send through to currently active UIModule
            # default handler just returns True, can be
            # overrided by UIModule to perform some action before
            # being unloaded, or return False to prevent unload
            if self.stack[-1].key_left():
                self.stack[-1].inactive()
                self.remove_from_stack()

    def key_up(self):
        if self.help_images is not None:
            self.help_image_index = (
                self.help_image_index - 1 if self.help_image_index > 0 else 0
            )
            self.update_screen(self.help_images[self.help_image_index])
            return

        if self.marking_menu_stack != []:
            self.mm_select(self.marking_menu_stack[-1].up)
            return

        self.stack[-1].key_up()

    def key_down(self):
        if self.help_images is not None:
            self.help_image_index = (
                self.help_image_index + 1
                if self.help_image_index < len(self.help_images) - 1
                else len(self.help_images) - 1
            )
            self.update_screen(self.help_images[self.help_image_index])
            return
        if self.marking_menu_stack != []:
            self.mm_select(self.marking_menu_stack[-1].down)
        else:
            self.stack[-1].key_down()

    def key_right(self):
        if self.help_images is not None:
            # Exit help
            self.help_images = None
            self.update()
            return
        if self.marking_menu_stack != []:
            self.mm_select(self.marking_menu_stack[-1].right)
        else:
            self.stack[-1].key_right()

    def mm_select(self, selected_item):
        if selected_item.label == "" or not selected_item.enabled:
            # Just bail out for non active menu items
            return

        self.flash_marking_menu_option(selected_item)

        if type(selected_item.callback) is MarkingMenu:
            self.marking_menu_stack.append(selected_item.callback)
            self.display_marking_menu()
        elif selected_item.label == "HELP":  # TODO: This needs to be changed for I18N
            self.exit_marking_menu()
            self.help_images = self.stack[-1].help()
            if self.help_images is not None:
                self.help_image_index = 0
                self.update_screen(self.help_images[0])
        elif selected_item.menu_jump is not None:
            self.exit_marking_menu()
            self.jump_to_label(selected_item.menu_jump)
        else:
            try:
                if (
                    selected_item.callback(self.marking_menu_stack[-1], selected_item)
                    is True
                ):
                    # Exit marking menu
                    self.exit_marking_menu()
                    self.update()
            except BaseException:
                print(selected_item)
                print(selected_item.callback)
                print(self.marking_menu_stack)
                raise
