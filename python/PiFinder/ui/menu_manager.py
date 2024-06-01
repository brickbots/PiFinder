from typing import Type, List
from PiFindner.ui.base import UIModule
from PiFinder.ui import menu_structure


class MenuManager:

    def __init__(
        self,
        display_class: Type[DisplayBase],
        camera_image,
        shared_state,
        command_queues,
        config_object,
    ):
        self.display_class = display_class
        self.shared_state = shared_state
        self.ui_state = shared_state.ui_state()
        self.camera_image = camera_image
        self.command_queues = command_queues

        self.stack: List[Type[UIModule]] = []

    def add_to_stack(self, item: dict) -> None:
        pass

    def update(self) -> None:
        self.stack[-1].update()
