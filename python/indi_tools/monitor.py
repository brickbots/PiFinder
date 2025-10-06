#!/usr/bin/env python3
"""
INDI Property Monitor Script

This script connects to an INDI server and continuously monitors all devices and their properties,
displaying real-time updates of all property values. It's designed to be a comprehensive monitoring
tool that shows all available data from all connected INDI devices.

Features:
- Monitors all devices on the INDI server
- Displays all property types (Number, Text, Switch, Light, Blob)
- Shows real-time updates as they occur
- Color-coded output for different property types
- Configurable update interval and display options
- Can filter by device name or property type
- Curses-based display with split screen layout
- Special focus on properties with %m format specifier and MOUNT_AXES

Display Modes:
- Traditional: Simple console output with coordinate table
- Curses: Split-screen interface with scrolling updates (top) and format properties (bottom)

Usage:
    python monitor.py [options]

    Options:
        --host HOST       INDI server host (default: localhost)
        --port PORT       INDI server port (default: 7624)
        --device DEVICE   Monitor only specific device
        --type TYPE       Monitor only specific property type (Number, Text, Switch, Light, Blob)
        --interval SEC    Update interval in seconds (default: 2.0)
        --verbose         Show debug information
        --no-color        Disable colored output
        --curses          Use curses-based display interface (press 'q' to quit)

Curses Display Layout:
    - Top area: Scrolling list of recent property updates
    - Bottom area: Properties with %m format specifier or MOUNT_AXES (shows 2 widgets each)
    - Status line: Summary statistics at the bottom
    - Automatic window size adaptation and color coding for changed values
"""

import PyIndi
import time
import sys
import argparse
import threading
import curses
import re
import copy
from datetime import datetime
from collections import defaultdict, deque


class IndiMonitor(PyIndi.BaseClient):
    """
    Enhanced INDI client for comprehensive property monitoring.

    This client monitors all devices and properties, maintaining a registry
    of all current values and displaying updates in real-time.
    """

    def __init__(
        self,
        device_filter=None,
        type_filter=None,
        use_color=True,
        verbose=False,
        use_curses=False,
    ):
        """
        Initialize the INDI monitor client.

        Args:
            device_filter (str): Only monitor this device (None for all devices)
            type_filter (str): Only monitor this property type (None for all types)
            use_color (bool): Use colored output for different property types
            verbose (bool): Show detailed debug information
            use_curses (bool): Use curses-based display interface
        """
        super(IndiMonitor, self).__init__()

        # Configuration
        self.device_filter = device_filter
        self.type_filter = type_filter
        self.use_color = use_color
        self.verbose = verbose
        self.use_curses = use_curses

        # State tracking
        self.devices = {}
        self.properties = {}
        self.connected_devices = set()
        self.update_count = 0
        self.start_time = time.time()

        # Coordinate tracking for change detection
        self.coordinate_values = {}  # Track current coordinate values
        self.previous_coordinate_values = {}  # Track previous values for change detection

        # Curses display tracking
        self.stdscr = None
        self.update_log = deque(
            maxlen=100
        )  # Scrolling updates with (message, count, timestamp)
        self.last_message = None  # Track last message for deduplication
        self.format_properties = {}  # Properties with %m format or MOUNT_AXES
        self.previous_format_values = {}  # For change detection
        self.screen_height = 0
        self.screen_width = 0

        # Thread synchronization
        self.lock = threading.Lock()

        # Color codes for different property types (if enabled)
        if self.use_color and not self.use_curses:
            self.colors = {
                "Number": "\033[92m",  # Green
                "Text": "\033[94m",  # Blue
                "Switch": "\033[93m",  # Yellow
                "Light": "\033[95m",  # Magenta
                "Blob": "\033[96m",  # Cyan
                "Device": "\033[91m",  # Red
                "Changed": "\033[43m",  # Yellow background for changed values
                "Reset": "\033[0m",  # Reset
            }
        else:
            self.colors = defaultdict(str)  # Empty strings for no color

        # Curses color pairs (will be initialized when curses starts)
        self.color_pairs = {}

    def init_curses(self, stdscr):
        """Initialize curses display."""
        self.stdscr = stdscr
        curses.curs_set(0)  # Hide cursor
        stdscr.nodelay(1)  # Non-blocking input

        # Initialize colors if supported
        if curses.has_colors() and self.use_color:
            curses.start_color()
            curses.use_default_colors()

            # Define color pairs
            curses.init_pair(1, curses.COLOR_GREEN, -1)  # Number
            curses.init_pair(2, curses.COLOR_BLUE, -1)  # Text
            curses.init_pair(3, curses.COLOR_YELLOW, -1)  # Switch
            curses.init_pair(4, curses.COLOR_MAGENTA, -1)  # Light
            curses.init_pair(5, curses.COLOR_CYAN, -1)  # Blob
            curses.init_pair(6, curses.COLOR_RED, -1)  # Device
            curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_YELLOW)  # Changed

            self.color_pairs = {
                "Number": curses.color_pair(1),
                "Text": curses.color_pair(2),
                "Switch": curses.color_pair(3),
                "Light": curses.color_pair(4),
                "Blob": curses.color_pair(5),
                "Device": curses.color_pair(6),
                "Changed": curses.color_pair(7),
            }

        self.update_screen_size()

    def update_screen_size(self):
        """Update screen dimensions."""
        if self.stdscr:
            self.screen_height, self.screen_width = self.stdscr.getmaxyx()

    def get_color(self, prop_type):
        """Safely get color code for property type."""
        if self.use_curses:
            return self.color_pairs.get(prop_type, 0)
        return self.colors.get(prop_type, self.colors.get("Reset", ""))

    def has_format_specifier(self, prop):
        """Check if property has %m format specifier or is MOUNT_AXES."""
        prop_name = prop.getName()

        # Always include MOUNT_AXES
        if prop_name == "MOUNT_AXES":
            return True

        # Check for %m format specifier in Number properties
        if prop.getType() == PyIndi.INDI_NUMBER:
            num_prop = PyIndi.PropertyNumber(prop)
            for widget in num_prop:
                format_str = widget.getFormat()
                if re.search(r"%\d*\.?\d*m", format_str):
                    return True

        return False

    def add_update_message(self, message):
        """Add a message to the update log with deduplication."""
        with self.lock:
            current_time = time.time()

            # Check if this is the same as the last message
            if (
                self.update_log
                and len(self.update_log) > 0
                and self.update_log[-1][0] == message
            ):
                # Same message - increment count and update timestamp
                last_msg, count, _ = self.update_log[-1]
                self.update_log[-1] = (last_msg, count + 1, current_time)
            else:
                # New message - add with count of 1
                self.update_log.append((message, 1, current_time))

    def format_coordinate_value(self, prop_name, widget_name, value):
        """Format coordinate values in human-readable format."""
        # Check if this is an RA/DEC coordinate property
        coord_properties = [
            "TARGET_EOD_COORD",
            "EQUATORIAL_EOD_COORD",
            "EQUATORIAL_COORD",
            "GEOGRAPHIC_COORD",
            "TELESCOPE_COORD",
            "HORIZONTAL_COORD",
        ]

        ra_widgets = ["RA", "LONG"]  # RA and longitude use hours
        dec_widgets = ["DEC", "LAT"]  # DEC and latitude use degrees

        # Check if this property contains coordinates
        is_coord_property = any(
            coord_prop in prop_name for coord_prop in coord_properties
        )

        if is_coord_property:
            if any(ra_widget in widget_name for ra_widget in ra_widgets):
                # Format as hours:minutes:seconds (RA/longitude)
                return self.decimal_hours_to_hms(value)
            elif any(dec_widget in widget_name for dec_widget in dec_widgets):
                # Format as degrees°minutes'seconds'' (DEC/latitude)
                return self.decimal_degrees_to_dms(value)

        # Return original value if not a coordinate
        return value

    def decimal_hours_to_hms(self, decimal_hours):
        """Convert decimal hours to HH:MM:SS.S format."""
        # Handle negative hours
        sign = "-" if decimal_hours < 0 else ""
        decimal_hours = abs(decimal_hours)

        hours = int(decimal_hours)
        remaining = (decimal_hours - hours) * 60
        minutes = int(remaining)
        seconds = (remaining - minutes) * 60

        return f"{sign}{hours:02d}h{minutes:02d}m{seconds:04.1f}s"

    def decimal_degrees_to_dms(self, decimal_degrees):
        """Convert decimal degrees to DD°MM'SS.S'' format."""
        # Handle negative degrees
        sign = "-" if decimal_degrees < 0 else "+"
        decimal_degrees = abs(decimal_degrees)

        degrees = int(decimal_degrees)
        remaining = (decimal_degrees - degrees) * 60
        minutes = int(remaining)
        seconds = (remaining - minutes) * 60

        return f"{sign}{degrees:02d}°{minutes:02d}'{seconds:04.1f}''"

    def log(self, message, level="INFO"):
        """Log a message with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if self.verbose or level == "INFO":
            print(f"[{timestamp}] {level}: {message}")

    def newDevice(self, device):
        """Called when a new device is discovered."""
        device_name = device.getDeviceName()

        # Apply device filter
        if self.device_filter and device_name != self.device_filter:
            return

        with self.lock:
            self.devices[device_name] = device

        print(
            f"{self.get_color('Device')}=== NEW DEVICE: {device_name} ==={self.get_color('Reset')}"
        )
        self.log(f"Discovered device: {device_name}")

    def removeDevice(self, device):
        """Called when a device is removed."""
        device_name = device.getDeviceName()

        with self.lock:
            if device_name in self.devices:
                del self.devices[device_name]
            if device_name in self.connected_devices:
                self.connected_devices.remove(device_name)

        print(
            f"{self.get_color('Device')}=== REMOVED DEVICE: {device_name} ==={self.get_color('Reset')}"
        )
        self.log(f"Removed device: {device_name}")

    def newProperty(self, prop):
        """Called when a new property is discovered."""
        device_name = prop.getDeviceName()
        prop_name = prop.getName()
        prop_type = prop.getTypeAsString()

        # Apply filters
        if self.device_filter and device_name != self.device_filter:
            return
        if self.type_filter and prop_type != self.type_filter:
            return

        prop_key = f"{device_name}.{prop_name}"

        with self.lock:
            self.properties[prop_key] = {
                "property": prop,
                "type": prop_type,
                "device": device_name,
                "name": prop_name,
                "last_update": time.time(),
            }

        if not self.use_curses:
            print(
                f"{self.get_color(prop_type)}--- NEW PROPERTY: {device_name}.{prop_name} ({prop_type}) ---{self.get_color('Reset')}"
            )
            self.log(f"New property: {prop_key} ({prop_type})")
            # Display initial values
            self._display_property_values(prop, is_update=False)
        else:
            # Add to update log for curses display
            self.add_update_message(f"NEW: {device_name}.{prop_name} ({prop_type})")

        # Track initial coordinate values
        self._track_coordinate_changes(prop)

        # Track format properties for curses display
        if self.use_curses and self.has_format_specifier(prop):
            self._track_format_property(prop)

    def updateProperty(self, prop):
        """Called when a property value is updated."""
        device_name = prop.getDeviceName()
        prop_name = prop.getName()
        prop_type = prop.getTypeAsString()

        # Apply filters
        if self.device_filter and device_name != self.device_filter:
            return
        if self.type_filter and prop_type != self.type_filter:
            return

        prop_key = f"{device_name}.{prop_name}"

        with self.lock:
            if prop_key in self.properties:
                self.properties[prop_key]["last_update"] = time.time()
            self.update_count += 1

        # Track coordinate changes for the table display
        self._track_coordinate_changes(prop)

        # Track format properties for curses display
        if self.use_curses and self.has_format_specifier(prop):
            self._track_format_property(prop)
            # Add to update log
            self.add_update_message(f"UPD: {device_name}.{prop_name}")

        # Track connection status
        if prop_name == "CONNECTION":
            self._check_connection_status(device_name, prop)

    def removeProperty(self, prop):
        """Called when a property is removed."""
        device_name = prop.getDeviceName()
        prop_name = prop.getName()
        prop_type = prop.getTypeAsString()
        prop_key = f"{device_name}.{prop_name}"

        with self.lock:
            if prop_key in self.properties:
                del self.properties[prop_key]

        print(
            f"{self.get_color(prop_type)}--- REMOVED PROPERTY: {device_name}.{prop_name} ({prop_type}) ---{self.get_color('Reset')}"
        )
        self.log(f"Removed property: {prop_key}")

    def newMessage(self, device, message_id):
        """Called when a new message arrives."""
        device_name = device.getDeviceName()
        if self.device_filter and device_name != self.device_filter:
            return

        message = device.messageQueue(message_id)
        print(f"📧 MESSAGE from {device_name}: {message}")
        self.log(f"Message from {device_name}: {message}")

    def serverConnected(self):
        """Called when connected to the INDI server."""
        print(f"🟢 Connected to INDI server at {self.getHost()}:{self.getPort()}")
        self.log("Connected to INDI server")

    def serverDisconnected(self, exit_code):
        """Called when disconnected from the INDI server."""
        print(f"🔴 Disconnected from INDI server (exit code: {exit_code})")
        self.log(f"Disconnected from INDI server (exit code: {exit_code})")

    def _display_property_values(self, prop, is_update=False):
        """Display all values for a given property."""
        device_name = prop.getDeviceName()
        prop_name = prop.getName()
        prop_type = prop.getTypeAsString()

        indent = "    "
        update_symbol = "🔄" if is_update else "✨"

        print(f"{indent}{update_symbol} Property: {prop_name}")
        print(f"{indent}   Device: {device_name}")
        print(f"{indent}   Type: {prop_type}")
        print(f"{indent}   State: {prop.getStateAsString()}")
        print(f"{indent}   Group: {prop.getGroupName()}")
        print(f"{indent}   Timestamp: {prop.getTimestamp()}")

        # Display values based on property type
        if prop.getType() == PyIndi.INDI_NUMBER:
            num_prop = PyIndi.PropertyNumber(prop)
            print(f"{indent}   Values:")
            for widget in num_prop:
                raw_value = widget.getValue()
                format_str = widget.getFormat()
                min_val = widget.getMin()
                max_val = widget.getMax()
                step = widget.getStep()

                # Format coordinate values in human-readable format
                formatted_value = self.format_coordinate_value(
                    prop_name, widget.getName(), raw_value
                )

                print(f"{indent}     • {widget.getName()} ({widget.getLabel()})")
                if formatted_value != raw_value:
                    # Show both formatted and raw value for coordinates
                    print(
                        f"{indent}       Value: {formatted_value} ({raw_value:.6f}) (format: {format_str})"
                    )
                else:
                    print(f"{indent}       Value: {raw_value} (format: {format_str})")
                print(f"{indent}       Range: {min_val} - {max_val} (step: {step})")

        elif prop.getType() == PyIndi.INDI_TEXT:
            text_prop = PyIndi.PropertyText(prop)
            print(f"{indent}   Values:")
            for widget in text_prop:
                text = widget.getText()
                print(
                    f"{indent}     • {widget.getName()} ({widget.getLabel()}): '{text}'"
                )

        elif prop.getType() == PyIndi.INDI_SWITCH:
            switch_prop = PyIndi.PropertySwitch(prop)
            print(f"{indent}   Rule: {switch_prop.getRuleAsString()}")
            print(f"{indent}   Values:")
            for widget in switch_prop:
                state = widget.getStateAsString()
                symbol = "🟢" if state == "On" else "🔴"
                print(
                    f"{indent}     • {widget.getName()} ({widget.getLabel()}): {symbol} {state}"
                )

        elif prop.getType() == PyIndi.INDI_LIGHT:
            light_prop = PyIndi.PropertyLight(prop)
            print(f"{indent}   Values:")
            for widget in light_prop:
                state = widget.getStateAsString()
                symbols = {"Idle": "⚪", "Ok": "🟢", "Busy": "🟡", "Alert": "🔴"}
                symbol = symbols.get(state, "❓")
                print(
                    f"{indent}     • {widget.getName()} ({widget.getLabel()}): {symbol} {state}"
                )

        elif prop.getType() == PyIndi.INDI_BLOB:
            blob_prop = PyIndi.PropertyBlob(prop)
            print(f"{indent}   Values:")
            for widget in blob_prop:
                size = widget.getSize()
                format_str = widget.getFormat()
                print(f"{indent}     • {widget.getName()} ({widget.getLabel()})")
                print(f"{indent}       Size: {size} bytes, Format: {format_str}")

        print()  # Empty line for readability

    def _track_coordinate_changes(self, prop):
        """Track coordinate property changes for the table display."""
        device_name = prop.getDeviceName()
        prop_name = prop.getName()

        # Check if this is a coordinate property
        coord_properties = [
            "TARGET_EOD_COORD",
            "EQUATORIAL_EOD_COORD",
            "EQUATORIAL_COORD",
            "GEOGRAPHIC_COORD",
            "TELESCOPE_COORD",
            "HORIZONTAL_COORD",
        ]

        if (
            any(coord_prop in prop_name for coord_prop in coord_properties)
            and prop.getType() == PyIndi.INDI_NUMBER
        ):
            prop_key = f"{device_name}.{prop_name}"
            num_prop = PyIndi.PropertyNumber(prop)

            with self.lock:
                # Store previous values
                if prop_key in self.coordinate_values:
                    self.previous_coordinate_values[prop_key] = self.coordinate_values[
                        prop_key
                    ].copy()

                # Update current values
                current_values = {}
                for widget in num_prop:
                    widget_name = widget.getName()
                    value = widget.getValue()
                    current_values[widget_name] = value

                self.coordinate_values[prop_key] = current_values

    def _track_format_property(self, prop):
        """Track properties with %m format specifier or MOUNT_AXES."""
        device_name = prop.getDeviceName()
        prop_name = prop.getName()
        prop_key = f"{device_name}.{prop_name}"

        if prop.getType() == PyIndi.INDI_NUMBER:
            num_prop = PyIndi.PropertyNumber(prop)

            with self.lock:
                # Store previous values for change detection
                if prop_key in self.format_properties:
                    self.previous_format_values[prop_key] = copy.deepcopy(
                        self.format_properties[prop_key]
                    )

                # Update current values
                current_values = {}
                for widget in num_prop:
                    widget_name = widget.getName()
                    value = widget.getValue()
                    format_str = widget.getFormat()
                    current_values[widget_name] = {
                        "value": value,
                        "format": format_str,
                        "label": widget.getLabel(),
                    }

                self.format_properties[prop_key] = current_values

    def _check_connection_status(self, device_name, prop):
        """Check and update device connection status."""
        switch_prop = PyIndi.PropertySwitch(prop)
        if switch_prop.isValid():
            is_connected = False
            for widget in switch_prop:
                if widget.getName() == "CONNECT" and widget.getStateAsString() == "On":
                    is_connected = True
                    break

            with self.lock:
                if is_connected:
                    if device_name not in self.connected_devices:
                        self.connected_devices.add(device_name)
                        print(f"🔗 Device {device_name} CONNECTED")
                else:
                    if device_name in self.connected_devices:
                        self.connected_devices.remove(device_name)
                        print(f"⛓️‍💥 Device {device_name} DISCONNECTED")

    def print_status_summary(self):
        """Print status summary - use curses or traditional display."""
        if self.use_curses:
            self.update_curses_display()
        else:
            self._print_traditional_summary()

    def _print_traditional_summary(self):
        """Print a single line status summary followed by coordinate table."""
        with self.lock:
            uptime = time.time() - self.start_time
            device_count = len(self.devices)
            connected_count = len(self.connected_devices)
            property_count = len(self.properties)

        # Clear screen and move cursor to top
        print("\033[2J\033[H", end="")

        # Single line summary
        summary = f"📊 Uptime: {uptime:.1f}s | Devices: {connected_count}/{device_count} | Properties: {property_count} | Updates: {self.update_count} | Server: {self.getHost()}:{self.getPort()}"
        if self.device_filter:
            summary += f" | Filter: {self.device_filter}"
        print(summary)

        # Coordinate table
        self._print_coordinate_table()

    def update_curses_display(self):
        """Update the curses-based display."""
        if not self.stdscr:
            return

        try:
            self.update_screen_size()
            self.stdscr.clear()

            # Calculate layout
            status_lines = 1  # Bottom status line
            format_props_count = len(self.format_properties)
            format_area_lines = min(
                format_props_count + 2, self.screen_height // 3
            )  # +2 for headers
            update_area_lines = self.screen_height - format_area_lines - status_lines

            # Draw top scrolling area (updates)
            self._draw_update_area(0, update_area_lines)

            # Draw bottom format properties area
            self._draw_format_area(update_area_lines, format_area_lines)

            # Draw status line at bottom
            self._draw_status_line(self.screen_height - 1)

            self.stdscr.refresh()

        except curses.error:
            # Handle terminal too small or other curses errors
            pass

    def _draw_update_area(self, start_y, height):
        """Draw the scrolling updates area."""
        if height < 2:
            return

        # Header
        header = "=== Latest Updates ==="
        self.stdscr.addstr(start_y, 0, header[: self.screen_width - 1], curses.A_BOLD)

        # Recent updates (most recent first)
        with self.lock:
            recent_updates = list(self.update_log)[-height + 1 :]

        for i, update_entry in enumerate(recent_updates):
            y = start_y + 1 + i
            if y >= start_y + height:
                break

            # Extract message, count, and timestamp
            if isinstance(update_entry, tuple) and len(update_entry) >= 2:
                message, count, _ = update_entry  # timestamp not used in display
                if count > 1:
                    display_text = f"{message} ({count})"
                else:
                    display_text = message
            else:
                # Handle legacy format (just strings)
                display_text = str(update_entry)

            # Truncate if too long
            if len(display_text) >= self.screen_width:
                display_text = display_text[: self.screen_width - 4] + "..."

            try:
                self.stdscr.addstr(y, 0, display_text)
            except curses.error:
                break

    def _draw_format_area(self, start_y, height):
        """Draw the format properties area."""
        if height < 2:
            return

        # Header
        header = "=== Format Properties (%m and MOUNT_AXES) ==="
        try:
            self.stdscr.addstr(
                start_y, 0, header[: self.screen_width - 1], curses.A_BOLD
            )
        except curses.error:
            return

        current_y = start_y + 1

        with self.lock:
            format_data = self.format_properties.copy()
            prev_data = self.previous_format_values.copy()

        for prop_key, widgets in format_data.items():
            if current_y >= start_y + height - 1:
                break

            # Property header
            device_name, prop_name = prop_key.split(".", 1)
            prop_header = f"{device_name}.{prop_name}:"

            try:
                self.stdscr.addstr(
                    current_y,
                    2,
                    prop_header[: self.screen_width - 3],
                    self.get_color("Device"),
                )
                current_y += 1
            except curses.error:
                break

            # Widget values (up to 2 widgets as specified)
            widget_count = 0
            for widget_name, widget_data in widgets.items():
                if widget_count >= 2 or current_y >= start_y + height - 1:
                    break

                value = widget_data["value"]
                format_str = widget_data["format"]
                label = widget_data["label"]

                # Check if value changed
                changed = False
                if (
                    prop_key in prev_data
                    and widget_name in prev_data[prop_key]
                    and "value" in prev_data[prop_key][widget_name]
                ):
                    prev_value = prev_data[prop_key][widget_name]["value"]
                    changed = abs(value - prev_value) > 1e-6

                # Format value according to INDI format specifier
                if re.search(r"%\d*\.?\d*m", format_str):
                    # Use INDI coordinate formatting
                    formatted_value = self.format_coordinate_value(
                        prop_name, widget_name, value
                    )
                else:
                    # Use the format string directly
                    try:
                        formatted_value = format_str % value
                    except (TypeError, ValueError):
                        formatted_value = str(value)

                # Create display line
                widget_line = f"  {label}: {formatted_value}"
                widget_line = widget_line[: self.screen_width - 1]

                # Apply color if changed
                color = self.get_color("Changed") if changed else 0

                try:
                    self.stdscr.addstr(current_y, 4, widget_line, color)
                    current_y += 1
                    widget_count += 1
                except curses.error:
                    break

    def _draw_status_line(self, y):
        """Draw the status line at the bottom."""
        with self.lock:
            uptime = time.time() - self.start_time
            device_count = len(self.devices)
            connected_count = len(self.connected_devices)
            property_count = len(self.properties)

        status = f"Up: {uptime:.0f}s | Dev: {connected_count}/{device_count} | Props: {property_count} | Updates: {self.update_count} | {self.getHost()}:{self.getPort()}"

        if self.device_filter:
            status += f" | Filter: {self.device_filter}"

        # Truncate to fit screen
        status = status[: self.screen_width - 1]

        try:
            self.stdscr.addstr(y, 0, status, curses.A_REVERSE)
        except curses.error:
            pass

    def _print_coordinate_table(self):
        """Print a table of current coordinate values with change highlighting."""
        with self.lock:
            coord_data = self.coordinate_values.copy()
            prev_data = self.previous_coordinate_values.copy()

        if not coord_data:
            print("No coordinate properties found")
            return

        # Table header
        print("┌" + "─" * 40 + "┬" + "─" * 25 + "┬" + "─" * 25 + "┐")
        print(f"│{'Property':<40}│{'RA/Long':<25}│{'DEC/Lat':<25}│")
        print("├" + "─" * 40 + "┼" + "─" * 25 + "┼" + "─" * 25 + "┤")

        # Table rows
        for prop_key, values in coord_data.items():
            # Extract device and property name
            parts = prop_key.split(".", 1)
            if len(parts) == 2:
                device_name, prop_name = parts
                display_name = f"{device_name}.{prop_name}"
            else:
                display_name = prop_key

            # Truncate if too long
            if len(display_name) > 38:
                display_name = display_name[:35] + "..."

            # Get coordinate values
            ra_value = ""
            dec_value = ""
            ra_changed = False
            dec_changed = False

            for widget_name, value in values.items():
                # Check if value changed
                changed = False
                if prop_key in prev_data and widget_name in prev_data[prop_key]:
                    changed = abs(value - prev_data[prop_key][widget_name]) > 1e-6

                # Format coordinate value
                formatted_value = self.format_coordinate_value(
                    prop_name, widget_name, value
                )

                # Assign to RA or DEC
                if any(ra_widget in widget_name for ra_widget in ["RA", "LONG"]):
                    ra_value = formatted_value
                    ra_changed = changed
                elif any(dec_widget in widget_name for dec_widget in ["DEC", "LAT"]):
                    dec_value = formatted_value
                    dec_changed = changed

            # Ensure values fit in columns (do this before applying color codes)
            if len(ra_value) > 23:
                ra_value = ra_value[:20] + "..."
            if len(dec_value) > 23:
                dec_value = dec_value[:20] + "..."

            # Apply color coding for changes
            ra_display = ra_value
            dec_display = dec_value

            if self.use_color:
                if ra_changed:
                    ra_display = f"{self.get_color('Changed')}{ra_value}{self.get_color('Reset')}"
                if dec_changed:
                    dec_display = f"{self.get_color('Changed')}{dec_value}{self.get_color('Reset')}"

            # For colored text, we need to manually pad since the color codes mess up string formatting
            if self.use_color and (ra_changed or dec_changed):
                ra_padding = 25 - len(ra_value)
                dec_padding = 25 - len(dec_value)
                ra_formatted = ra_display + " " * ra_padding
                dec_formatted = dec_display + " " * dec_padding
                print(f"│{display_name:<40}│{ra_formatted}│{dec_formatted}│")
            else:
                print(f"│{display_name:<40}│{ra_display:<25}│{dec_display:<25}│")

        print("└" + "─" * 40 + "┴" + "─" * 25 + "┴" + "─" * 25 + "┘")


def main():
    """Main function to run the INDI monitor."""
    parser = argparse.ArgumentParser(
        description="INDI Property Monitor - Monitor all INDI devices and properties"
    )
    parser.add_argument(
        "--host", default="localhost", help="INDI server host (default: localhost)"
    )
    parser.add_argument(
        "--port", type=int, default=7624, help="INDI server port (default: 7624)"
    )
    parser.add_argument("--device", help="Monitor only specific device")
    parser.add_argument(
        "--type",
        choices=["Number", "Text", "Switch", "Light", "Blob"],
        help="Monitor only specific property type",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Status summary interval in seconds (default: 2.0)",
    )
    parser.add_argument("--verbose", action="store_true", help="Show debug information")
    parser.add_argument(
        "--no-color", action="store_true", help="Disable colored output"
    )
    parser.add_argument(
        "--curses", action="store_true", help="Use curses-based display interface"
    )

    args = parser.parse_args()

    # Create the monitor client
    monitor = IndiMonitor(
        device_filter=args.device,
        type_filter=args.type,
        use_color=not args.no_color,
        verbose=args.verbose,
        use_curses=args.curses,
    )

    # Connect to the INDI server
    monitor.setServer(args.host, args.port)

    if not args.curses:
        print("🚀 Starting INDI Property Monitor...")
        print(f"   Server: {args.host}:{args.port}")
        if args.device:
            print(f"   Device Filter: {args.device}")
        if args.type:
            print(f"   Type Filter: {args.type}")
        print("   Press Ctrl+C to stop monitoring")
        print()

    if not monitor.connectServer():
        print(f"❌ Failed to connect to INDI server at {args.host}:{args.port}")
        print("   Make sure the INDI server is running. Try:")
        print("   indiserver indi_simulator_telescope indi_simulator_ccd")
        sys.exit(1)

    def run_monitor_loop():
        """Main monitoring loop."""
        try:
            # Wait for initial discovery
            time.sleep(2)

            # Monitor loop
            last_status_time = time.time()

            while True:
                time.sleep(1)

                # Check for resize in curses mode
                if args.curses and monitor.stdscr:
                    try:
                        key = monitor.stdscr.getch()
                        if key == ord("q") or key == ord("Q"):
                            break
                        elif key == curses.KEY_RESIZE:
                            monitor.update_screen_size()
                    except curses.error:
                        pass

                # Print periodic status summary
                current_time = time.time()
                if current_time - last_status_time >= args.interval:
                    monitor.print_status_summary()
                    last_status_time = current_time

        except KeyboardInterrupt:
            if not args.curses:
                print("\n🛑 Monitoring stopped by user")
        except Exception as e:
            if not args.curses:
                print(f"\n💥 Unexpected error: {e}")
        finally:
            if not args.curses:
                print("🔌 Disconnecting from INDI server...")
            monitor.disconnectServer()
            if not args.curses:
                print("✅ Monitor shutdown complete")

    if args.curses:
        # Run in curses mode
        def curses_main(stdscr):
            monitor.init_curses(stdscr)
            run_monitor_loop()

        curses.wrapper(curses_main)
    else:
        # Run in traditional mode
        run_monitor_loop()


if __name__ == "__main__":
    main()
