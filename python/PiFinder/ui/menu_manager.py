import time
from typing import Union
from PIL import Image
from PiFinder.ui.base import UIModule
from PiFinder.ui import menu_structure
from PiFinder.displays import DisplayBase
from PiFinder.ui.marking_menus import (
    MarkingMenu,
    MarkingMenuOption,
    render_marking_menu,
)


def find_menu_by_label(label: str):
    """
    Returns the FIRST instance of a menu dict
    with the specified key.  labels in the menu
    struct should be unique.

    Returns None is not found
    """
    # stack = [iter(menu_structure.pifinder_menu.items())]
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
        self._stack_anim_duration: float = 0.1
        self._stack_anim_counter: float = 0
        self._stack_anim_direction: int = 0

        self.stack: list[type[UIModule]] = []
        self.add_to_stack(menu_structure.pifinder_menu)

        self.marking_menu_stack: list[MarkingMenu] = []
        self.marking_menu_bg: Union[Image.Image, None] = None

        # This will be populated if we are in 'help' mode
        self.help_images: Union[None, list[Image.Image]] = None
        self.help_image_index = 0

    def remove_from_stack(self) -> None:
        if len(self.stack) > 1:
            self._stack_top_image = self.stack[-1].screen.copy()
            self.stack.pop()
            self.stack[-1].active()  # type: ignore[call-arg]
            self._stack_anim_counter = time.time() + self._stack_anim_duration
            self._stack_anim_direction = 1

    def add_to_stack(self, item: dict) -> None:
        """
        Adds a new module to the stack by creating
        a new instance of the specified class, passing
        in all the required UI Module arguments + the
        item dict
        """
        if item.get("state") is not None:
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
                )
            )
            if item.get("stateful", False):
                item["state"] = self.stack[-1]

        self.stack[-1].active()  # type: ignore[call-arg]
        if len(self.stack) > 1:
            self._stack_anim_counter = time.time() + self._stack_anim_duration
            self._stack_anim_direction = -1

    def message(self, message: str, timeout: float) -> None:
        self.stack[-1].message(message, timeout)  # type: ignore[arg-type]

    def screengrab(self) -> None:
        self.stack[-1].screengrab()  # type: ignore[call-arg]

    def jump_to_label(self, label: str) -> None:
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
                    (self.display_class.resolution[0] / self._stack_anim_duration)
                    * (
                        self._stack_anim_duration
                        - (self._stack_anim_counter - time.time())
                    )
                )
            else:
                top_image = self.stack[-1].screen
                bottom_image = self.stack[-2].screen
                top_pos = int(
                    (self.display_class.resolution[0] / self._stack_anim_duration)
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
        if time.time() < self.ui_state.message_timeout():
            return None

        screen_to_display = screen_image.convert(self.display_class.device.mode)
        self.display_class.device.display(screen_to_display)

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
        pass

    def key_long_left(self):
        """
        Return to top of menu
        """
        if self.help_images is not None:
            # Exit help
            self.help_images = None
            self.update()

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
        elif selected_item.label == "HELP":
            self.exit_marking_menu()
            self.help_images = self.stack[-1].help()
            self.help_image_index = 0
            self.update_screen(self.help_images[0])
        elif selected_item.menu_jump is not None:
            self.exit_marking_menu()
            self.jump_to_label(selected_item.menu_jump)
        else:
            if (
                selected_item.callback(self.marking_menu_stack[-1], selected_item)
                is True
            ):
                # Exit marking menu
                self.exit_marking_menu()
                self.update()
