#!/usr/bin/env python3
"""
INDI Event Replayer - Mock INDI client that replays recorded events.

This module provides a mock INDI client that reads a recorded event stream
and replays it to simulate INDI server behavior. Useful for testing and
development without requiring actual hardware.
"""

import json
import time
import logging
import threading
from typing import Dict, Any, List, Optional
import PyIndi

# Import the property factory
try:
    from property_factory import advanced_factory
except ImportError:
    # Fallback if imported from different context
    import sys
    import os

    current_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, current_dir)
    from property_factory import advanced_factory


class MockIndiDevice:
    """Mock INDI device that simulates device properties and behavior."""

    def __init__(self, device_name: str, driver_name: str = None):
        self.device_name = device_name
        self.driver_name = driver_name or device_name
        self.driver_exec = driver_name or device_name
        self.driver_version = "1.0"
        self.properties = {}
        self.message_queue = []

    def getDeviceName(self) -> str:
        return self.device_name

    def getDriverName(self) -> str:
        return self.driver_name

    def getDriverExec(self) -> str:
        return self.driver_exec

    def getDriverVersion(self) -> str:
        return self.driver_version

    def messageQueue(self, index: int) -> str:
        if 0 <= index < len(self.message_queue):
            return self.message_queue[index]
        return ""

    def addMessage(self, message: str):
        self.message_queue.append(message)


class MockIndiProperty:
    """Mock INDI property that holds property metadata and widgets."""

    def __init__(self, prop_data: Dict[str, Any]):
        self.name = prop_data["name"]
        self.device_name = prop_data["device_name"]
        self.type_str = prop_data["type"]
        self.state = prop_data["state"]
        self.permission = prop_data["permission"]
        self.group = prop_data["group"]
        self.label = prop_data["label"]
        self.rule = prop_data.get("rule")
        self.widgets = prop_data["widgets"]

        # Map type string to PyIndi constants
        self.type_map = {
            "Text": PyIndi.INDI_TEXT,
            "Number": PyIndi.INDI_NUMBER,
            "Switch": PyIndi.INDI_SWITCH,
            "Light": PyIndi.INDI_LIGHT,
            "Blob": PyIndi.INDI_BLOB,
        }

    def getName(self) -> str:
        return self.name

    def getDeviceName(self) -> str:
        return self.device_name

    def getType(self) -> int:
        return self.type_map.get(self.type_str, PyIndi.INDI_TEXT)

    def getTypeAsString(self) -> str:
        return self.type_str

    def getStateAsString(self) -> str:
        return self.state

    def getPermAsString(self) -> str:
        return self.permission

    def getGroupName(self) -> str:
        return self.group

    def getLabel(self) -> str:
        return self.label

    def getRuleAsString(self) -> str:
        return self.rule or "AtMostOne"


class IndiEventReplayer:
    """
    Event replayer that simulates INDI server behavior by replaying recorded events.

    This class reads a JSON Lines event file and replays the events to a connected
    INDI client, simulating the original server behavior with configurable timing.
    """

    def __init__(self, event_file: str, target_client: PyIndi.BaseClient):
        self.logger = logging.getLogger("IndiEventReplayer")
        self.event_file = event_file
        self.target_client = target_client
        self.events = []
        self.devices = {}
        self.properties = {}
        self.is_playing = False
        self.start_time = None
        self.time_scale = 1.0  # 1.0 = real-time, 2.0 = 2x speed, 0.5 = half speed
        self.playback_thread = None

        self._load_events()

    def _load_events(self) -> None:
        """Load events from the JSON Lines file."""
        try:
            with open(self.event_file, "r") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    try:
                        event = json.loads(line)
                        self.events.append(event)
                    except json.JSONDecodeError as e:
                        self.logger.error(f"Invalid JSON on line {line_num}: {e}")

            # Sort events by relative time to ensure proper order
            self.events.sort(key=lambda x: x.get("relative_time", 0))
            self.logger.info(f"Loaded {len(self.events)} events from {self.event_file}")

        except FileNotFoundError:
            self.logger.error(f"Event file not found: {self.event_file}")
            raise
        except Exception as e:
            self.logger.error(f"Failed to load events: {e}")
            raise

    def set_time_scale(self, scale: float) -> None:
        """Set the playback time scale (1.0 = real-time, 2.0 = 2x speed)."""
        self.time_scale = scale
        self.logger.info(f"Time scale set to {scale}x")

    def _create_mock_device(self, device_data: Dict[str, Any]) -> MockIndiDevice:
        """Create a mock device from event data."""
        device = MockIndiDevice(
            device_data["device_name"], device_data.get("driver_name")
        )
        return device

    def _create_mock_property(self, prop_data: Dict[str, Any]):
        """Create a property object from event data.

        Now creates a property that's compatible with PyIndi PropertyNumber,
        PropertyText, etc. wrapper classes while still providing access to test data.
        """
        return advanced_factory.create_mock_property_with_data(prop_data)

    def _process_event(self, event: Dict[str, Any]) -> None:
        """Process a single event and call the appropriate client method."""
        event_type = event["event_type"]
        data = event["data"]

        try:
            if event_type == "server_connected":
                # Simulate server connection
                self.target_client.serverConnected()

            elif event_type == "server_disconnected":
                # Simulate server disconnection
                self.target_client.serverDisconnected(data.get("exit_code", 0))

            elif event_type == "new_device":
                # Create and register mock device
                device = self._create_mock_device(data)
                self.devices[data["device_name"]] = device
                self.target_client.newDevice(device)

            elif event_type == "remove_device":
                # Remove device
                device_name = data["device_name"]
                if device_name in self.devices:
                    device = self.devices[device_name]
                    self.target_client.removeDevice(device)
                    del self.devices[device_name]

            elif event_type == "new_property":
                # Create and register mock property
                prop = self._create_mock_property(data)
                prop_key = f"{data['device_name']}.{data['name']}"
                self.properties[prop_key] = prop
                self.target_client.newProperty(prop)

            elif event_type == "update_property":
                # Update existing property
                prop = self._create_mock_property(data)
                prop_key = f"{data['device_name']}.{data['name']}"
                self.properties[prop_key] = prop
                self.target_client.updateProperty(prop)

            elif event_type == "remove_property":
                # Remove property
                prop_key = f"{data['device_name']}.{data['name']}"
                if prop_key in self.properties:
                    prop = self.properties[prop_key]
                    self.target_client.removeProperty(prop)
                    del self.properties[prop_key]

            elif event_type == "new_message":
                # Send message
                device_name = data["device_name"]
                if device_name in self.devices:
                    device = self.devices[device_name]
                    device.addMessage(data["message"])
                    self.target_client.newMessage(device, data["message"])

        except Exception as e:
            self.logger.error(f"Error processing {event_type} event: {e}")

    def _playback_loop(self) -> None:
        """Main playback loop that processes events with timing."""
        self.start_time = time.time()
        self.logger.info("Starting event playback")

        for event in self.events:
            if not self.is_playing:
                break

            # Calculate when this event should be played
            event_time = event.get("relative_time", 0)
            scaled_time = event_time / self.time_scale
            target_time = self.start_time + scaled_time

            # Wait until it's time to play this event
            current_time = time.time()
            if target_time > current_time:
                sleep_time = target_time - current_time
                time.sleep(sleep_time)

            if not self.is_playing:
                break

            # Process the event
            self._process_event(event)
            self.logger.debug(
                f"Played event {event['event_number']}: {event['event_type']}"
            )

        self.logger.info("Playback completed")

    def start_playback(self, blocking: bool = False) -> None:
        """Start event playback."""
        if self.is_playing:
            self.logger.warning("Playback already in progress")
            return

        self.is_playing = True

        if blocking:
            self._playback_loop()
        else:
            self.playback_thread = threading.Thread(target=self._playback_loop)
            self.playback_thread.daemon = True
            self.playback_thread.start()

    def stop_playback(self) -> None:
        """Stop event playback."""
        self.is_playing = False
        if self.playback_thread and self.playback_thread.is_alive():
            self.playback_thread.join(timeout=1.0)

    def get_device(self, device_name: str) -> Optional[MockIndiDevice]:
        """Get a mock device by name."""
        return self.devices.get(device_name)

    def get_property(
        self, device_name: str, property_name: str
    ) -> Optional[MockIndiProperty]:
        """Get a mock property by device and property name."""
        prop_key = f"{device_name}.{property_name}"
        return self.properties.get(prop_key)

    def list_devices(self) -> List[str]:
        """Get list of all device names."""
        return list(self.devices.keys())

    def list_properties(self, device_name: str = None) -> List[str]:
        """Get list of properties, optionally filtered by device."""
        if device_name:
            return [
                key.split(".", 1)[1]
                for key in self.properties.keys()
                if key.startswith(f"{device_name}.")
            ]
        return list(self.properties.keys())


def main():
    """Example usage of the event replayer."""
    import argparse

    parser = argparse.ArgumentParser(description="Replay INDI events to a client")
    parser.add_argument("event_file", help="JSON Lines event file to replay")
    parser.add_argument(
        "--speed", type=float, default=1.0, help="Playback speed multiplier"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=log_level
    )

    logger = logging.getLogger("main")

    # Create a simple test client that just logs events
    class TestClient(PyIndi.BaseClient):
        def __init__(self):
            super().__init__()
            self.logger = logging.getLogger("TestClient")

        def newDevice(self, device):
            self.logger.info(f"Device: {device.getDeviceName()}")

        def newProperty(self, prop):
            self.logger.info(f"Property: {prop.getName()} on {prop.getDeviceName()}")

        def updateProperty(self, prop):
            self.logger.info(f"Updated: {prop.getName()} on {prop.getDeviceName()}")

        def newMessage(self, device, message):
            self.logger.info(f"Message from {device.getDeviceName()}: {message}")

        def serverConnected(self):
            self.logger.info("Server connected")

        def serverDisconnected(self, code):
            self.logger.info(f"Server disconnected (code: {code})")

    # Create client and replayer
    client = TestClient()
    replayer = IndiEventReplayer(args.event_file, client)
    replayer.set_time_scale(args.speed)

    try:
        logger.info(f"Starting replay of {args.event_file} at {args.speed}x speed")
        replayer.start_playback(blocking=True)
    except KeyboardInterrupt:
        logger.info("Replay stopped by user")
        replayer.stop_playback()
    except Exception as e:
        logger.error(f"Error during replay: {e}")


if __name__ == "__main__":
    main()
