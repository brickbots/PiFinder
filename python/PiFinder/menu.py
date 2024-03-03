import logging


class MenuScroller:
    """
    A class to handle the scrolling of the menu items.
    Input is a list of options, output is the current range of options to display.
    """

    endstop = "---"

    def __init__(self, menu_items, visible_count=10):
        self.set_items(menu_items, visible_count)
        self.current_pos = 0
        self.start_index = 0
        self.end_index = 0

    def set_items(self, menu_items, visible_count=10):
        self.menu_items = menu_items
        # self.menu_items.append(self.endstop)
        self.visible_count = visible_count

    def up(self):
        """
        Move the selected item up
        """
        if self.current_pos > 0:
            self.current_pos -= 1
        else:
            self.current_pos = len(self.menu_items) - self.visible_count

    def down(self):
        """
        Move the selected item down
        """
        if self.current_pos >= len(self.menu_items) - self.visible_count:
            self.current_pos = 0
        else:
            self.current_pos += 1

    def get_selected(self):
        """
        Return the currently selected item
        """
        return self.menu_items[self.current_pos]

    def get_selected_pos(self):
        """
        Return the currently selected item
        """
        return self.current_pos

    def get_options_window(self):
        self.current_pos = max(0, min(self.current_pos, len(self.menu_items) - 1))

        # Ensure self.current_pos is within the bounds of the self.menu_items
        # If all menu options fit within the visible window, no need to scroll
        if len(self.menu_items) <= self.visible_count:
            return self.menu_items, 0, len(self.menu_items)

        # Highlighted item causes the window to move to include the item
        self.start_index = self.current_pos
        self.end_index = self.start_index + self.visible_count

        # Return the slice of menu options to display, along with start and end indices
        return self.menu_items[self.start_index : self.end_index]

    def get_options_window2(self):
        menu_options = self.menu_items
        visible_count = self.visible_count
        highlighted_index = self.current_pos
        # Calculate the start and end indices of the menu slice to display
        if highlighted_index < visible_count // 2:
            # Highlighted option is in the first half of the visible menu
            start_index = 0
        elif highlighted_index > len(menu_options) - visible_count // 2 - 1:
            # Highlighted option is in the last half of the visible menu
            start_index = max(0, len(menu_options) - visible_count)
        else:
            # Highlighted option is in the middle of the visible menu
            start_index = highlighted_index - visible_count // 2

        end_index = min(start_index + visible_count, len(menu_options))
        self.start_index = start_index
        self.end_index = end_index
        print(f"start_index: {start_index}, end_index: {end_index}")

        # Return the slice of menu options to display
        return menu_options[start_index:end_index]

    def get_options_window_old(self):
        """
        Return the range of options to display
        """
        start_index = self.current_pos
        if self.current_pos > int(self.visible_count / 2):
            start_index = self.current_pos - int(self.visible_count / 2)
        end_index = self.start_index + self.visible_count
        if end_index > len(self.menu_items):
            start_index = start_index - (end_index - len(self.menu_items))
        if start_index < 0:
            start_index = 0
        self.start_index = start_index
        self.end_index = end_index
        return self.menu_items[start_index:end_index]

    def __str__(self):
        result = f"{self.menu_items=}, {self.current_pos=}, {self.visible_count=}, {self.start_index=}, {self.end_index=}"
        # result += '\n' + ", ".join(self.get_options_window())
        # result = ", ".join(self.menu_items)
        # result = "["
        #
        # for i, option in enumerate(self.menu_items):
        #     if i == self.current_pos:
        #         result += f" <{option}>"
        #     elif i < self.start_index or i >= self.end_index:
        #         result += f" /{option}/"
        #     else:
        #         result += f" {option}"
        # result += " ]"
        return result

    def __repr__(self):
        return self.__str__()
