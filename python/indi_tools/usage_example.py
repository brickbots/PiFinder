#!/usr/bin/env python3
"""
Simple usage example demonstrating INDI event recording and replay.

This example shows how to integrate the event recording/replay system
with your own INDI client for testing and development.
"""

import time
import logging
import os
import sys
import PyIndi

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from event_recorder import IndiEventRecorder
from event_replayer import IndiEventReplayer


class ExampleIndiClient(PyIndi.BaseClient):
    """
    Example INDI client that demonstrates how to use the recording/replay system.
    """

    def __init__(self, name="ExampleClient"):
        super().__init__()
        self.name = name
        self.logger = logging.getLogger(f"ExampleClient-{name}")
        self.connected_devices = {}
        self.telescope_device = None
        self.telescope_coord_prop = None

    def newDevice(self, device):
        """Handle new device discovery."""
        device_name = device.getDeviceName()
        self.connected_devices[device_name] = device
        self.logger.info(f"New device discovered: {device_name}")

        # Look for telescope devices
        if "telescope" in device_name.lower() or "simulator" in device_name.lower():
            self.telescope_device = device
            self.logger.info(f"Telescope device found: {device_name}")

    def newProperty(self, prop):
        """Handle new property creation."""
        device_name = prop.getDeviceName()
        prop_name = prop.getName()
        self.logger.info(
            f"New property: {device_name}.{prop_name} ({prop.getTypeAsString()})"
        )

        # Look for telescope coordinate properties
        if (
            self.telescope_device
            and device_name == self.telescope_device.getDeviceName()
            and "COORD" in prop_name.upper()
        ):
            self.telescope_coord_prop = prop
            self.logger.info(f"Found telescope coordinates property: {prop_name}")

    def updateProperty(self, prop):
        """Handle property updates."""
        device_name = prop.getDeviceName()
        prop_name = prop.getName()

        # Log coordinate updates if this is our telescope
        if (
            self.telescope_coord_prop
            and prop.getName() == self.telescope_coord_prop.getName()
        ):
            self._log_telescope_coordinates(prop)
        else:
            self.logger.debug(f"Property updated: {device_name}.{prop_name}")

    def _log_telescope_coordinates(self, prop):
        """Log telescope coordinate updates."""
        if prop.getType() == PyIndi.INDI_NUMBER:
            coords = {}
            number_prop = PyIndi.PropertyNumber(prop)
            for widget in number_prop:
                coords[widget.getName()] = widget.getValue()

            ra = coords.get("RA", 0.0)
            dec = coords.get("DEC", 0.0)
            self.logger.info(f"Telescope coordinates: RA={ra:.6f}, DEC={dec:.6f}")

    def newMessage(self, device, message):
        """Handle device messages."""
        self.logger.info(f"Message from {device.getDeviceName()}: {message}")

    def serverConnected(self):
        """Handle server connection."""
        self.logger.info("Connected to INDI server")

    def serverDisconnected(self, code):
        """Handle server disconnection."""
        self.logger.info(f"Disconnected from INDI server (code: {code})")


def demo_live_recording():
    """Demonstrate recording events from a live INDI server."""
    print("=" * 60)
    print("DEMO 1: Recording from live INDI server")
    print("=" * 60)
    print()
    print("This demo will connect to an INDI server and record events.")
    print("Make sure you have an INDI server running:")
    print("  indiserver indi_simulator_telescope indi_simulator_ccd")
    print()

    if input("Press Enter to continue (or 'q' to skip): ").lower() == "q":
        return None

    # Record events for 5 seconds
    output_file = "demo_recording.jsonl"
    recorder = IndiEventRecorder(output_file)
    recorder.setServer("localhost", 7624)

    try:
        if not recorder.connectServer():
            print("❌ Could not connect to INDI server")
            print("   Please start: indiserver indi_simulator_telescope")
            return None

        print(f"📹 Recording events to {output_file} for 5 seconds...")
        time.sleep(5)

        recorder.disconnectServer()
        recorder.close()

        # Check what we recorded
        if os.path.exists(output_file):
            with open(output_file, "r") as f:
                lines = f.readlines()
            print(f"✅ Recorded {len(lines)} events")
            return output_file
        else:
            print("❌ Recording file not created")
            return None

    except Exception as e:
        print(f"❌ Error during recording: {e}")
        return None


def demo_replay(event_file):
    """Demonstrate replaying recorded events."""
    print("\n" + "=" * 60)
    print("DEMO 2: Replaying recorded events")
    print("=" * 60)
    print()
    print(f"This demo will replay events from {event_file}")
    print("and show how your client receives them.")
    print()

    if input("Press Enter to continue (or 'q' to skip): ").lower() == "q":
        return

    # Create our example client
    client = ExampleIndiClient("Demo")

    # Create replayer
    try:
        replayer = IndiEventReplayer(event_file, client)
        replayer.set_time_scale(2.0)  # 2x speed for demo

        print("🎬 Starting replay at 2x speed...")
        print("   Watch the log messages to see events being processed")
        print()

        start_time = time.time()
        replayer.start_playback(blocking=True)
        duration = time.time() - start_time

        print(f"\n✅ Replay completed in {duration:.2f} seconds")
        print(f"   Devices seen: {list(client.connected_devices.keys())}")

        if client.telescope_device:
            print(f"   Telescope found: {client.telescope_device.getDeviceName()}")

    except Exception as e:
        print(f"❌ Error during replay: {e}")


def demo_editing():
    """Demonstrate editing event streams."""
    print("\n" + "=" * 60)
    print("DEMO 3: Event stream editing")
    print("=" * 60)
    print()
    print("This demo shows how to edit recorded event streams.")
    print("We'll create a sample file and show its structure.")
    print()

    # Create a sample event file
    sample_file = "demo_sample.jsonl"
    import json

    sample_events = [
        {
            "timestamp": 1640995200.0,
            "relative_time": 0.0,
            "event_number": 0,
            "event_type": "server_connected",
            "data": {"host": "localhost", "port": 7624},
        },
        {
            "timestamp": 1640995201.0,
            "relative_time": 1.0,
            "event_number": 1,
            "event_type": "new_device",
            "data": {
                "device_name": "Demo Telescope",
                "driver_name": "demo_telescope",
                "driver_exec": "demo_telescope",
                "driver_version": "1.0",
            },
        },
        {
            "timestamp": 1640995202.0,
            "relative_time": 2.0,
            "event_number": 2,
            "event_type": "new_message",
            "data": {
                "device_name": "Demo Telescope",
                "message": "Hello from the demo telescope!",
            },
        },
    ]

    # Write sample file in proper JSON Lines format
    with open(sample_file, "w") as f:
        for event in sample_events:
            f.write(f"{json.dumps(event, separators=(',', ':'))}\n")

    print(f"📝 Created sample event file: {sample_file}")
    print("\nFile contents (JSON Lines format - one JSON object per line):")
    print("-" * 60)

    with open(sample_file, "r") as f:
        print(f.read())

    print("About JSON Lines format:")
    print("• Each line contains one complete JSON event object")
    print("• No commas between lines (unlike JSON arrays)")
    print("• Easy to edit - add/remove lines without syntax issues")
    print("• Streamable and appendable")
    print()
    print("To edit this file:")
    print("• Change 'relative_time' values to adjust timing")
    print("• Modify 'message' content to test different scenarios")
    print("• Add new events or remove entire lines")
    print("• Change device names or properties")
    print("• Each line must be valid JSON")
    print()
    print("Then replay the edited file to test your changes!")

    # Clean up
    os.unlink(sample_file)


def main():
    """Main demo function."""
    # Setup logging
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO
    )

    print("🔭 INDI Event Recording and Replay System Demo")
    print()
    print("This demo shows how to:")
    print("1. Record events from a live INDI server")
    print("2. Replay recorded events to test your client")
    print("3. Edit event streams for custom scenarios")
    print()

    # Demo 1: Live recording
    recorded_file = demo_live_recording()

    # Demo 2: Replay (use recorded file or fallback to sample)
    if recorded_file:
        demo_replay(recorded_file)
    else:
        print("\n⚠️  Skipping replay demo (no recording available)")
        print("   To see replay in action, start an INDI server and re-run")

    # Demo 3: Editing
    demo_editing()

    # Cleanup
    if recorded_file and os.path.exists(recorded_file):
        os.unlink(recorded_file)

    print("\n" + "=" * 60)
    print("✅ Demo completed!")
    print()
    print("Next steps:")
    print("• Record your own telescope sessions")
    print("• Create test scenarios by editing event files")
    print("• Integrate replay into your test suite")
    print("• Use for development without hardware")
    print()
    print("For more information, see README.md and EVENT_FORMAT.md")


if __name__ == "__main__":
    main()
