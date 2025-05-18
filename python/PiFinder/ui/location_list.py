from PiFinder.ui.textentry import UITextEntry
from PiFinder.ui.text_menu import UITextMenu


class UILocationList(UITextMenu):
    """UI for managing saved locations"""

    __title__ = "Saved Locations"

    def __init__(self, *args, **kwargs):
        # Set up menu items before calling parent init
        self.locations = kwargs["config_object"].locations.locations
        kwargs["item_definition"] = self.create_menu_definition()
        super().__init__(*args, **kwargs)
        self.action_menu_active = False
        self.actions = ["Load", "Rename", "Delete"]
        self.action_index = 0

    def create_menu_definition(self):
        """Create menu definition from locations"""
        items = []
        for loc in self.locations:
            items.append(
                {
                    "name": loc.name,  # Just show the name in the main list
                    "location": loc,
                    "value": loc,
                }
            )

        return {"name": "Locations", "select": "single", "items": items}

    def draw_action_menu(self):
        """Draw the action menu for selected location"""
        self.clear_screen()
        draw_pos = self.display_class.titlebar_height + 2

        loc = self.item_definition["items"][self._current_item_index]["value"]
        # Draw name in bold
        self.draw.text(
            (0, draw_pos),
            f"{loc.name}",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
        draw_pos += 12

        # Draw coordinates in base font
        self.draw.text(
            (0, draw_pos),
            f"{loc.latitude:.2f}°, {loc.longitude:.2f}°, {loc.height:.0f}m",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 16

        # Draw actions
        for i, action in enumerate(self.actions):
            color = 255 if i == self.action_index else 128
            self.draw.text(
                (0, draw_pos),
                action,
                font=self.fonts.base.font,
                fill=self.colors.get(color),
            )
            draw_pos += 10

    def perform_action(self):
        """Execute the selected action on the current location"""
        location = self.item_definition["items"][self._current_item_index]["value"]

        if self.action_menu_active and 0 <= self.action_index < len(self.actions):
            action = self.actions[self.action_index]

            if action == "Load":
                # Set location as current
                self.command_queues["gps"].put(
                    (
                        "fix",
                        {
                            "lat": location.latitude,
                            "lon": location.longitude,
                            "altitude": location.height,
                            "source": f"CONFIG: {location.name}",
                            "lock": True,
                            "lock_type": 2,
                            "error_in_m": location.error_in_m,
                        },
                    )
                )
                # Set as default if desired
                if not location.is_default:
                    self.config_object.locations.set_default(location)
                    self.config_object.save_locations()

                # Show confirmation message
                self.message(f"Loaded: {location.name}", timeout=2)

                # Return True twice to pop two levels
                self.action_menu_active = False  # Exit action menu mode
                return True  # Signal to MenuManager to pop this screen

            elif action == "Delete":
                self.config_object.locations.remove_location(location)
                self.config_object.save_locations()
                self.locations = self.config_object.locations.locations

                # Recreate menu definition to update the items displayed
                self.item_definition = self.create_menu_definition()
                # Update the menu items list from the new definition
                self._menu_items = [x["name"] for x in self.item_definition["items"]]

                # Ensure the current item index is valid
                if self._current_item_index >= len(self.item_definition["items"]):
                    self._current_item_index = max(
                        0, len(self.item_definition["items"]) - 1
                    )

                self.selected_index = None
                self.message(f"Deleted: {location.name}", timeout=2)
                self.action_menu_active = False
                return False

            elif action == "Rename":
                # Create text entry for new name
                item_definition = {
                    "name": "Location Name",
                    "class": UITextEntry,
                    "mode": "text_entry",
                    "initial_text": location.name,
                    "callback": lambda name: self.rename_location(location, name),
                }
                self.add_to_stack(item_definition)
                return False

    def rename_location(self, location, new_name):
        """Handle location rename callback"""
        location.name = new_name
        self.config_object.save_locations()
        self.message(f"Renamed to:\n{new_name}", timeout=2)
        self.action_menu_active = False  # Return to location list view
        return True  # Return to location list

    def key_up(self):
        if self.action_menu_active:
            self.action_index = (self.action_index - 1) % len(self.actions)
        else:
            super().key_up()

    def key_down(self):
        if self.action_menu_active:
            self.action_index = (self.action_index + 1) % len(self.actions)
        else:
            super().key_down()

    def key_right(self):
        if not self.action_menu_active and self._current_item_index < len(
            self._menu_items
        ):
            self.action_menu_active = True
            self.action_index = 0
            return False
        elif self.action_menu_active:
            return self.perform_action()
        return False

    def key_left(self):
        if self.action_menu_active:
            self.action_menu_active = False
            return False
        return True

    def update(self, force=False):
        if self.action_menu_active:
            self.draw_action_menu()
        else:
            super().update(force)
        return self.screen_update()
