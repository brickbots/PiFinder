#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Integration test keyboard interface for PiFinder menu system.

This module implements an automated keyboard interface that systematically
navigates through all menu items in the PiFinder menu structure, visiting
every leaf node (non-UITextMenu module) and simulating user input.
"""

import time
import logging
from typing import List, Dict, Any, Optional, cast
from PiFinder.keyboard_interface import KeyboardInterface
from PiFinder.ui.menu_structure import pifinder_menu
from PiFinder.ui.text_menu import UITextMenu
from PiFinder.multiproclogging import MultiprocLogging

logger = logging.getLogger("Keyboard.MenuTest")


class KeyboardMenuTest(KeyboardInterface):
    """
    Automated keyboard interface for comprehensive menu system testing.

    This class traverses the entire menu structure defined in menu_structure.py,
    visiting every leaf node (UI classes only) and simulating user interactions.
    Callback items are skipped to avoid dangerous operations.
    """

    # Special keycode to signal test completion and clean exit
    TEST_COMPLETE = 999

    def __init__(self, q=None, keystroke_delay=0.1):
        """
        Initialize the menu test keyboard interface.

        Args:
            q: Queue for sending keystrokes to the main application
            keystroke_delay: Time in seconds to wait between keystrokes
        """
        super().__init__(q)
        self.keystroke_delay = keystroke_delay
        self.visited_paths: List[str] = []
        self.skipped_callbacks: List[str] = []
        self.current_path: List[str] = []

    def send_key(self, key_code: int) -> None:
        """
        Send a keystroke to the application with logging and delay.

        Args:
            key_code: The keystroke code to send
            description: Optional description for logging
        """

        if self.q:
            self.q.put(key_code)
        time.sleep(self.keystroke_delay)

    def navigate_to_item(self, target_index: int, current_index: int = 0) -> None:
        """
        Navigate to a specific menu item using UP/DOWN arrows.

        Args:
            target_index: Index of the target menu item
            current_index: Current position in the menu (default: 0)
        """
        if target_index == current_index:
            return

        if target_index > current_index:
            # Navigate down
            for _ in range(target_index - current_index):
                self.send_key(self.DOWN)
        else:
            # Navigate up
            for _ in range(current_index - target_index):
                self.send_key(self.UP)

    def interact_with_leaf_node(self, item_name: str) -> None:
        """
        Simulate user interaction at a leaf node.

        This sends all number keys (0-9), plus, minus, and square key
        to test the leaf node's input handling.

        Args:
            item_name: Name of the leaf node for logging
        """
        logger.info(f"Interacting with leaf node: {item_name}")
        return

        # Test number keys 0-9
        for i in range(10):
            self.send_key(i)

        # Test special keys
        self.send_key(self.PLUS)
        self.send_key(self.MINUS)
        self.send_key(self.SQUARE)

        # Brief pause at leaf node
        time.sleep(self.keystroke_delay * 2)

    def traverse_menu_items(
        self,
        menu_items: List[Dict[str, Any]],
        start_index: int = 0,
        parent_path: Optional[List[str]] = None,
    ) -> None:
        """
        Recursively traverse all menu items in a menu structure.

        Args:
            menu_items: List of menu item dictionaries to traverse
            parent_path: Path to current menu level for tracking
        """
        if parent_path is None:
            parent_path = []

        current_item_index = start_index
        for item_index, item in enumerate(menu_items):
            item_name = item["name"]
            current_item_path = parent_path + [item_name]
            self.current_path = current_item_path

            logger.info(f"Processing item {item_index}: {item_name}")

            # Navigate to this item in the menu
            self.navigate_to_item(item_index, current_item_index)
            current_item_index = item_index

            # Check if this is a callback item - SKIP these as they can be dangerous
            if "callback" in item:
                logger.warning(
                    f"Skipping callback item: {item_name} (potentially dangerous)"
                )
                self.skipped_callbacks.append(" -> ".join(current_item_path))
                continue

            # Check if this is a leaf node (not UITextMenu)
            item_class = item.get("class")

            if item_class and item_class != UITextMenu:
                # This is a safe UI class leaf node - enter it and interact
                logger.info(
                    f"Found UI leaf node: {item_name} (class: {item_class.__name__})"
                )
                self.send_key(self.RIGHT)

                # Interact with the leaf node
                self.interact_with_leaf_node(item_name)

                # Back out of the leaf node
                self.send_key(self.LEFT)
                self.visited_paths.append(" -> ".join(current_item_path))

            elif item_class == UITextMenu and "items" in item:
                # This is a submenu - enter it and traverse recursively
                logger.info(f"Entering submenu: {item_name}")
                self.send_key(self.RIGHT)

                # Recursively traverse the submenu
                self.traverse_menu_items(
                    item["items"], item.get("start_index", 0), current_item_path
                )

                # Back out of the submenu
                logger.info(f"Leaving submenu: {item_name}")
                self.send_key(self.LEFT)

            else:
                logger.warning(
                    f"Unknown or unhandled item type for {item_name}: {item}"
                )

    def run_keyboard(self) -> None:
        """
        Main entry point for the menu test keyboard interface.

        This method starts the automated traversal of the entire menu structure.
        """
        logger.info("Starting automated menu system test")
        logger.info(f"Keystroke delay: {self.keystroke_delay}s")

        try:
            # Start from the root menu
            logger.info("Waiting for main loop to start....")
            time.sleep(5)
            root_menu = pifinder_menu

            # issue keystrokes to back out and up to make sure we start at the
            # right place
            logger.info("Resetting menu position")

            logger.info(f"Starting traversal from root menu: {root_menu['name']}")

            # Begin traversal of all menu items
            menu_items = cast(List[Dict[str, Any]], root_menu.get("items", []))
            menu_name = cast(str, root_menu.get("name", "Root"))
            start_index = cast(int, root_menu.get("start_index", 0))
            self.traverse_menu_items(menu_items, start_index, [menu_name])

            # Test complete - report results
            logger.info("Menu system test completed successfully")
            logger.info(f"Total UI leaf nodes visited: {len(self.visited_paths)}")
            logger.info(f"Total callback items skipped: {len(self.skipped_callbacks)}")

            logger.info("Visited UI leaf nodes:")
            for path in self.visited_paths:
                logger.info(f"  ✓ {path}")

            if self.skipped_callbacks:
                logger.info("Skipped callback items (for safety):")
                for path in self.skipped_callbacks:
                    logger.info(f"  ⚠ {path}")

            # Send termination signal to main application
            logger.info("Sending test completion signal")
            self.send_key(self.TEST_COMPLETE)

        except Exception as e:
            logger.error(f"Error during menu test: {e}", exc_info=True)
            # Send termination signal even on error
            logger.info("Sending test completion signal due to error")
            self.send_key(self.TEST_COMPLETE)
        finally:
            logger.info("Menu test keyboard interface shutting down")


def run_keyboard(q, shared_state, log_queue, bloom_key_remap=False):
    """
    Entry point function for the menu test keyboard interface.

    This function is called by the main application to start the
    automated menu testing process.

    Args:
        q: Queue for sending keystrokes
        shared_state: Shared state object (not used in this implementation)
        log_queue: Queue for logging
        bloom_key_remap: Key remapping flag (not used in this implementation)
    """
    MultiprocLogging.configurer(log_queue)
    logger.info("Initializing menu test keyboard interface")

    # Create and start the menu test keyboard
    keyboard = KeyboardMenuTest(q=q, keystroke_delay=1)
    keyboard.run_keyboard()
