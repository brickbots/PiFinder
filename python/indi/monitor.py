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

Usage:
    python monitor.py [options]

    Options:
        --host HOST       INDI server host (default: localhost)
        --port PORT       INDI server port (default: 7624)
        --device DEVICE   Monitor only specific device
        --type TYPE       Monitor only specific property type (Number, Text, Switch, Light, Blob)
        --interval SEC    Update interval in seconds (default: 1.0)
        --verbose         Show debug information
        --no-color        Disable colored output
"""

import PyIndi
import time
import sys
import argparse
import threading
from datetime import datetime
from collections import defaultdict


class IndiMonitor(PyIndi.BaseClient):
    """
    Enhanced INDI client for comprehensive property monitoring.

    This client monitors all devices and properties, maintaining a registry
    of all current values and displaying updates in real-time.
    """

    def __init__(self, device_filter=None, type_filter=None, use_color=True, verbose=False):
        """
        Initialize the INDI monitor client.

        Args:
            device_filter (str): Only monitor this device (None for all devices)
            type_filter (str): Only monitor this property type (None for all types)
            use_color (bool): Use colored output for different property types
            verbose (bool): Show detailed debug information
        """
        super(IndiMonitor, self).__init__()

        # Configuration
        self.device_filter = device_filter
        self.type_filter = type_filter
        self.use_color = use_color
        self.verbose = verbose

        # State tracking
        self.devices = {}
        self.properties = {}
        self.connected_devices = set()
        self.update_count = 0
        self.start_time = time.time()

        # Thread synchronization
        self.lock = threading.Lock()

        # Color codes for different property types (if enabled)
        if self.use_color:
            self.colors = {
                'Number': '\033[92m',    # Green
                'Text': '\033[94m',      # Blue
                'Switch': '\033[93m',    # Yellow
                'Light': '\033[95m',     # Magenta
                'Blob': '\033[96m',      # Cyan
                'Device': '\033[91m',    # Red
                'Reset': '\033[0m'       # Reset
            }
        else:
            self.colors = defaultdict(str)  # Empty strings for no color

    def get_color(self, prop_type):
        """Safely get color code for property type."""
        return self.colors.get(prop_type, self.colors.get('Reset', ''))

    def format_coordinate_value(self, prop_name, widget_name, value):
        """Format coordinate values in human-readable format."""
        # Check if this is an RA/DEC coordinate property
        coord_properties = [
            'TARGET_EOD_COORD', 'EQUATORIAL_EOD_COORD', 'EQUATORIAL_COORD',
            'GEOGRAPHIC_COORD', 'TELESCOPE_COORD', 'ON_COORD_SET'
        ]

        ra_widgets = ['RA', 'LONG']  # RA and longitude use hours
        dec_widgets = ['DEC', 'LAT']  # DEC and latitude use degrees

        # Check if this property contains coordinates
        is_coord_property = any(coord_prop in prop_name for coord_prop in coord_properties)

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

    def log(self, message, level='INFO'):
        """Log a message with timestamp."""
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        if self.verbose or level == 'INFO':
            print(f"[{timestamp}] {level}: {message}")

    def newDevice(self, device):
        """Called when a new device is discovered."""
        device_name = device.getDeviceName()

        # Apply device filter
        if self.device_filter and device_name != self.device_filter:
            return

        with self.lock:
            self.devices[device_name] = device

        print(f"{self.get_color('Device')}=== NEW DEVICE: {device_name} ==={self.get_color('Reset')}")
        self.log(f"Discovered device: {device_name}")

    def removeDevice(self, device):
        """Called when a device is removed."""
        device_name = device.getDeviceName()

        with self.lock:
            if device_name in self.devices:
                del self.devices[device_name]
            if device_name in self.connected_devices:
                self.connected_devices.remove(device_name)

        print(f"{self.get_color('Device')}=== REMOVED DEVICE: {device_name} ==={self.get_color('Reset')}")
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
                'property': prop,
                'type': prop_type,
                'device': device_name,
                'name': prop_name,
                'last_update': time.time()
            }

        print(f"{self.get_color(prop_type)}--- NEW PROPERTY: {device_name}.{prop_name} ({prop_type}) ---{self.get_color('Reset')}")
        self.log(f"New property: {prop_key} ({prop_type})")

        # Display initial values
        self._display_property_values(prop, is_update=False)

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
                self.properties[prop_key]['last_update'] = time.time()
            self.update_count += 1

        # print(f"{self.get_color(prop_type)}>>> UPDATE: {device_name}.{prop_name} ({prop_type}) <<<{self.get_color('Reset')}")

        # Display updated values
        # self._display_property_values(prop, is_update=True)

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

        print(f"{self.get_color(prop_type)}--- REMOVED PROPERTY: {device_name}.{prop_name} ({prop_type}) ---{self.get_color('Reset')}")
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
                formatted_value = self.format_coordinate_value(prop_name, widget.getName(), raw_value)

                print(f"{indent}     • {widget.getName()} ({widget.getLabel()})")
                if formatted_value != raw_value:
                    # Show both formatted and raw value for coordinates
                    print(f"{indent}       Value: {formatted_value} ({raw_value:.6f}) (format: {format_str})")
                else:
                    print(f"{indent}       Value: {raw_value} (format: {format_str})")
                print(f"{indent}       Range: {min_val} - {max_val} (step: {step})")

        elif prop.getType() == PyIndi.INDI_TEXT:
            text_prop = PyIndi.PropertyText(prop)
            print(f"{indent}   Values:")
            for widget in text_prop:
                text = widget.getText()
                print(f"{indent}     • {widget.getName()} ({widget.getLabel()}): '{text}'")

        elif prop.getType() == PyIndi.INDI_SWITCH:
            switch_prop = PyIndi.PropertySwitch(prop)
            print(f"{indent}   Rule: {switch_prop.getRuleAsString()}")
            print(f"{indent}   Values:")
            for widget in switch_prop:
                state = widget.getStateAsString()
                symbol = "🟢" if state == "On" else "🔴"
                print(f"{indent}     • {widget.getName()} ({widget.getLabel()}): {symbol} {state}")

        elif prop.getType() == PyIndi.INDI_LIGHT:
            light_prop = PyIndi.PropertyLight(prop)
            print(f"{indent}   Values:")
            for widget in light_prop:
                state = widget.getStateAsString()
                symbols = {"Idle": "⚪", "Ok": "🟢", "Busy": "🟡", "Alert": "🔴"}
                symbol = symbols.get(state, "❓")
                print(f"{indent}     • {widget.getName()} ({widget.getLabel()}): {symbol} {state}")

        elif prop.getType() == PyIndi.INDI_BLOB:
            blob_prop = PyIndi.PropertyBlob(prop)
            print(f"{indent}   Values:")
            for widget in blob_prop:
                size = widget.getSize()
                format_str = widget.getFormat()
                print(f"{indent}     • {widget.getName()} ({widget.getLabel()})")
                print(f"{indent}       Size: {size} bytes, Format: {format_str}")

        print()  # Empty line for readability

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
        """Print a summary of the current monitoring status."""
        with self.lock:
            uptime = time.time() - self.start_time
            device_count = len(self.devices)
            connected_count = len(self.connected_devices)
            property_count = len(self.properties)

        print(f"\n📊 MONITORING STATUS SUMMARY:")
        print(f"   Uptime: {uptime:.1f} seconds")
        print(f"   Total Devices: {device_count} (Connected: {connected_count})")
        print(f"   Total Properties: {property_count}")
        print(f"   Total Updates: {self.update_count}")
        print(f"   Server: {self.getHost()}:{self.getPort()}")

        if self.device_filter:
            print(f"   Device Filter: {self.device_filter}")
        if self.type_filter:
            print(f"   Type Filter: {self.type_filter}")
        print()


def main():
    """Main function to run the INDI monitor."""
    parser = argparse.ArgumentParser(description="INDI Property Monitor - Monitor all INDI devices and properties")
    parser.add_argument("--host", default="localhost", help="INDI server host (default: localhost)")
    parser.add_argument("--port", type=int, default=7624, help="INDI server port (default: 7624)")
    parser.add_argument("--device", help="Monitor only specific device")
    parser.add_argument("--type", choices=["Number", "Text", "Switch", "Light", "Blob"],
                       help="Monitor only specific property type")
    parser.add_argument("--interval", type=float, default=10.0,
                       help="Status summary interval in seconds (default: 10.0)")
    parser.add_argument("--verbose", action="store_true", help="Show debug information")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")

    args = parser.parse_args()

    # Create the monitor client
    monitor = IndiMonitor(
        device_filter=args.device,
        type_filter=args.type,
        use_color=not args.no_color,
        verbose=args.verbose
    )

    # Connect to the INDI server
    monitor.setServer(args.host, args.port)

    print(f"🚀 Starting INDI Property Monitor...")
    print(f"   Server: {args.host}:{args.port}")
    if args.device:
        print(f"   Device Filter: {args.device}")
    if args.type:
        print(f"   Type Filter: {args.type}")
    print(f"   Press Ctrl+C to stop monitoring\n")

    if not monitor.connectServer():
        print(f"❌ Failed to connect to INDI server at {args.host}:{args.port}")
        print("   Make sure the INDI server is running. Try:")
        print("   indiserver indi_simulator_telescope indi_simulator_ccd")
        sys.exit(1)

    try:
        # Wait for initial discovery
        time.sleep(2)

        # Monitor loop
        last_status_time = time.time()

        while True:
            time.sleep(1)

            # Print periodic status summary
            current_time = time.time()
            if current_time - last_status_time >= args.interval:
                monitor.print_status_summary()
                last_status_time = current_time

    except KeyboardInterrupt:
        print("\n🛑 Monitoring stopped by user")
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
    finally:
        print("🔌 Disconnecting from INDI server...")
        monitor.disconnectServer()
        print("✅ Monitor shutdown complete")


if __name__ == "__main__":
    main()