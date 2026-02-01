#!/usr/bin/env python3
"""
Test script for INDI event recording and replay functionality.

This script demonstrates how to use the event recorder and replayer
to capture INDI server events and replay them for testing.
"""

import os
import sys
import time
import logging
import json

# Add the parent directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from event_recorder import IndiEventRecorder
from event_replayer import IndiEventReplayer
import PyIndi


class TestRecordingIndiClient(PyIndi.BaseClient):
    """Test INDI client that logs all received events."""

    def __init__(self, name: str = "TestClient"):
        super().__init__()
        self.name = name
        self.logger = logging.getLogger(f"TestClient-{name}")
        self.events_received = []
        self.devices_seen = set()
        self.properties_seen = set()

    def _log_event(self, event_type: str, **kwargs):
        """Log an event and add it to our tracking list."""
        event_info = {"type": event_type, "timestamp": time.time(), **kwargs}
        self.events_received.append(event_info)
        self.logger.info(f"{event_type}: {kwargs}")

    def newDevice(self, device):
        self.devices_seen.add(device.getDeviceName())
        self._log_event(
            "NEW_DEVICE", device=device.getDeviceName(), driver=device.getDriverName()
        )

    def removeDevice(self, device):
        self._log_event("REMOVE_DEVICE", device=device.getDeviceName())

    def newProperty(self, prop):
        prop_key = f"{prop.getDeviceName()}.{prop.getName()}"
        self.properties_seen.add(prop_key)
        self._log_event(
            "NEW_PROPERTY",
            device=prop.getDeviceName(),
            property=prop.getName(),
            type=prop.getTypeAsString(),
        )

    def updateProperty(self, prop):
        self._log_event(
            "UPDATE_PROPERTY",
            device=prop.getDeviceName(),
            property=prop.getName(),
            state=prop.getStateAsString(),
        )

    def removeProperty(self, prop):
        self._log_event(
            "REMOVE_PROPERTY", device=prop.getDeviceName(), property=prop.getName()
        )

    def newMessage(self, device, message):
        self._log_event("NEW_MESSAGE", device=device.getDeviceName(), message=message)

    def serverConnected(self):
        self._log_event("SERVER_CONNECTED")

    def serverDisconnected(self, code):
        self._log_event("SERVER_DISCONNECTED", code=code)

    def get_stats(self):
        """Get statistics about events received."""
        event_counts = {}
        for event in self.events_received:
            event_type = event["type"]
            event_counts[event_type] = event_counts.get(event_type, 0) + 1

        return {
            "total_events": len(self.events_received),
            "event_counts": event_counts,
            "devices_seen": list(self.devices_seen),
            "properties_seen": list(self.properties_seen),
        }


def test_live_recording(duration: int = 5, output_file: str = None):
    """
    Test recording events from a live INDI server.

    Args:
        duration: How long to record (seconds)
        output_file: Where to save the recording
    """
    logger = logging.getLogger("test_live_recording")

    if output_file is None:
        output_file = f"test_recording_{int(time.time())}.jsonl"

    logger.info(f"Testing live recording for {duration} seconds")

    # Create recorder
    recorder = IndiEventRecorder(output_file)
    recorder.setServer("localhost", 7624)

    try:
        # Connect to server
        if not recorder.connectServer():
            logger.error("Could not connect to INDI server at localhost:7624")
            logger.error("Please start an INDI server first:")
            logger.error("  indiserver indi_simulator_telescope indi_simulator_ccd")
            return None

        logger.info(f"Recording to {output_file}...")
        time.sleep(duration)

        recorder.disconnectServer()
        recorder.close()

        # Check what we recorded
        if os.path.exists(output_file):
            with open(output_file, "r") as f:
                lines = f.readlines()
            logger.info(f"Recorded {len(lines)} events to {output_file}")
            return output_file
        else:
            logger.error("Recording file was not created")
            return None

    except Exception as e:
        logger.error(f"Error during recording: {e}")
        return None


def test_replay(event_file: str, speed: float = 1.0):
    """
    Test replaying events from a recorded file.

    Args:
        event_file: Path to the recorded events file
        speed: Playback speed multiplier
    """
    logger = logging.getLogger("test_replay")
    logger.info(f"Testing replay of {event_file} at {speed}x speed")

    # Create test client to receive replayed events
    client = TestRecordingIndiClient("Replay")

    # Create replayer
    try:
        replayer = IndiEventReplayer(event_file, client)
        replayer.set_time_scale(speed)

        # Start replay
        start_time = time.time()
        replayer.start_playback(blocking=True)
        duration = time.time() - start_time

        # Get statistics
        stats = client.get_stats()
        logger.info(f"Replay completed in {duration:.2f} seconds")
        logger.info(f"Events replayed: {stats['total_events']}")
        logger.info(f"Event breakdown: {stats['event_counts']}")
        logger.info(f"Devices seen: {stats['devices_seen']}")
        logger.info(f"Properties seen: {len(stats['properties_seen'])}")

        return stats

    except Exception as e:
        logger.error(f"Error during replay: {e}")
        return None


def test_mock_comparison():
    """Test that replayed events match original recording structure."""
    logger = logging.getLogger("test_mock_comparison")
    logger.info("Testing mock event generation")

    # Create a simple test event file
    test_events = [
        {
            "timestamp": time.time(),
            "relative_time": 0.0,
            "event_number": 0,
            "event_type": "server_connected",
            "data": {"host": "localhost", "port": 7624},
        },
        {
            "timestamp": time.time() + 1,
            "relative_time": 1.0,
            "event_number": 1,
            "event_type": "new_device",
            "data": {
                "device_name": "Test Telescope",
                "driver_name": "test_driver",
                "driver_exec": "test_driver",
                "driver_version": "1.0",
            },
        },
        {
            "timestamp": time.time() + 2,
            "relative_time": 2.0,
            "event_number": 2,
            "event_type": "new_property",
            "data": {
                "name": "CONNECTION",
                "device_name": "Test Telescope",
                "type": "Switch",
                "state": "Idle",
                "permission": "ReadWrite",
                "group": "Main Control",
                "label": "Connection",
                "rule": "OneOfMany",
                "widgets": [
                    {"name": "CONNECT", "label": "Connect", "state": "Off"},
                    {"name": "DISCONNECT", "label": "Disconnect", "state": "On"},
                ],
            },
        },
    ]

    # Write test file
    test_file = "test_mock_events.jsonl"
    try:
        with open(test_file, "w") as f:
            for event in test_events:
                f.write(f"{json.dumps(event)}\n")

        # Test replay
        stats = test_replay(test_file, speed=10.0)  # Fast replay

        # Cleanup
        os.unlink(test_file)

        if stats:
            logger.info("Mock comparison test passed")
            return True
        else:
            logger.error("Mock comparison test failed")
            return False

    except Exception as e:
        logger.error(f"Error in mock comparison test: {e}")
        return False


def create_sample_events():
    """Create a sample events file for demonstration."""
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
                "device_name": "Telescope Simulator",
                "driver_name": "indi_simulator_telescope",
                "driver_exec": "indi_simulator_telescope",
                "driver_version": "1.9",
            },
        },
        {
            "timestamp": 1640995202.0,
            "relative_time": 2.0,
            "event_number": 2,
            "event_type": "new_property",
            "data": {
                "name": "CONNECTION",
                "device_name": "Telescope Simulator",
                "type": "Switch",
                "state": "Idle",
                "permission": "ReadWrite",
                "group": "Main Control",
                "label": "Connection",
                "rule": "OneOfMany",
                "widgets": [
                    {"name": "CONNECT", "label": "Connect", "state": "Off"},
                    {"name": "DISCONNECT", "label": "Disconnect", "state": "On"},
                ],
            },
        },
        {
            "timestamp": 1640995203.0,
            "relative_time": 3.0,
            "event_number": 3,
            "event_type": "update_property",
            "data": {
                "name": "CONNECTION",
                "device_name": "Telescope Simulator",
                "type": "Switch",
                "state": "Ok",
                "permission": "ReadWrite",
                "group": "Main Control",
                "label": "Connection",
                "rule": "OneOfMany",
                "widgets": [
                    {"name": "CONNECT", "label": "Connect", "state": "On"},
                    {"name": "DISCONNECT", "label": "Disconnect", "state": "Off"},
                ],
            },
        },
        {
            "timestamp": 1640995204.0,
            "relative_time": 4.0,
            "event_number": 4,
            "event_type": "new_message",
            "data": {
                "device_name": "Telescope Simulator",
                "message": "Telescope simulator is online.",
            },
        },
    ]

    sample_file = "sample_events.jsonl"
    with open(sample_file, "w") as f:
        for event in sample_events:
            f.write(f"{json.dumps(event)}\n")

    return sample_file


def main():
    """Main test function."""
    import argparse

    parser = argparse.ArgumentParser(description="Test INDI recording and replay")
    parser.add_argument(
        "--mode",
        choices=["record", "replay", "test", "sample"],
        default="test",
        help="Test mode",
    )
    parser.add_argument("--file", help="Event file for replay mode")
    parser.add_argument(
        "--duration", type=int, default=5, help="Recording duration in seconds"
    )
    parser.add_argument(
        "--speed", type=float, default=1.0, help="Replay speed multiplier"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=log_level
    )

    logger = logging.getLogger("main")

    if args.mode == "record":
        logger.info("Starting live recording test")
        recorded_file = test_live_recording(args.duration)
        if recorded_file:
            logger.info(f"Recording saved to: {recorded_file}")
            logger.info(
                f"To replay: python {sys.argv[0]} --mode replay --file {recorded_file}"
            )

    elif args.mode == "replay":
        if not args.file:
            logger.error("Replay mode requires --file argument")
            sys.exit(1)
        logger.info("Starting replay test")
        test_replay(args.file, args.speed)

    elif args.mode == "sample":
        logger.info("Creating sample events file")
        sample_file = create_sample_events()
        logger.info(f"Sample events created: {sample_file}")
        logger.info(
            f"To replay: python {sys.argv[0]} --mode replay --file {sample_file}"
        )

    elif args.mode == "test":
        logger.info("Running comprehensive tests")

        # Test 1: Mock comparison
        logger.info("=" * 50)
        logger.info("Test 1: Mock event generation")
        test_mock_comparison()

        # Test 2: Sample replay
        logger.info("=" * 50)
        logger.info("Test 2: Sample event replay")
        sample_file = create_sample_events()
        test_replay(sample_file, speed=5.0)
        os.unlink(sample_file)

        logger.info("=" * 50)
        logger.info("All tests completed!")
        logger.info("To test with a live INDI server:")
        logger.info(f"  python {sys.argv[0]} --mode record --duration 10")


if __name__ == "__main__":
    main()
