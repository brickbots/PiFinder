#!/usr/bin/env python3
"""
INDI Event Recorder - Captures and records all events from an INDI server.

This module provides a PyIndi client that connects to an INDI server and records
all events to a JSON stream file. The recorded events can later be replayed
using the mock client.
"""

import json
import time
import logging
import sys
from typing import Dict, Any
import PyIndi


class IndiEventRecorder(PyIndi.BaseClient):
    """
    INDI client that records all events from the server to a JSON stream file.

    The recorder captures all INDI protocol events including device discovery,
    property changes, messages, and connection events. Each event is timestamped
    and written to a JSON Lines format file for easy editing and replay.
    """

    def __init__(self, output_file: str = "indi_events.jsonl"):
        super().__init__()
        self.logger = logging.getLogger("IndiEventRecorder")
        self.output_file = output_file
        self.start_time = time.time()
        self.event_count = 0

        # Open output file for writing
        try:
            self.file_handle = open(self.output_file, "w")
            self.logger.info(f"Recording events to {self.output_file}")
        except Exception as e:
            self.logger.error(f"Failed to open output file {self.output_file}: {e}")
            raise

    def _write_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Write an event to the output file in JSON Lines format."""
        try:
            event = {
                "timestamp": time.time(),
                "relative_time": time.time() - self.start_time,
                "event_number": self.event_count,
                "event_type": event_type,
                "data": data,
            }

            json_line = json.dumps(event, separators=(",", ":"))
            self.file_handle.write(json_line + "\n")
            self.file_handle.flush()  # Ensure immediate write

            self.event_count += 1
            self.logger.debug(f"Recorded event {self.event_count}: {event_type}")

        except Exception as e:
            self.logger.error(f"Failed to write event: {e}")

    def _extract_property_data(self, prop) -> Dict[str, Any]:
        """Extract property data based on property type."""
        prop_data = {
            "name": prop.getName(),
            "device_name": prop.getDeviceName(),
            "type": prop.getTypeAsString(),
            "state": prop.getStateAsString(),
            "permission": getattr(prop, "getPermAsString", lambda: "Unknown")(),
            "group": getattr(prop, "getGroupName", lambda: "Unknown")(),
            "label": getattr(prop, "getLabel", lambda: prop.getName())(),
            "rule": getattr(prop, "getRuleAsString", lambda: None)(),
            "widgets": [],
        }

        # Extract widget values based on property type
        try:
            if prop.getType() == PyIndi.INDI_TEXT:
                text_prop = PyIndi.PropertyText(prop)
                for widget in text_prop:
                    prop_data["widgets"].append(
                        {
                            "name": getattr(widget, "getName", lambda: "Unknown")(),
                            "label": getattr(
                                widget,
                                "getLabel",
                                lambda: getattr(widget, "getName", lambda: "Unknown")(),
                            )(),
                            "value": getattr(widget, "getText", lambda: "")(),
                        }
                    )

            elif prop.getType() == PyIndi.INDI_NUMBER:
                number_prop = PyIndi.PropertyNumber(prop)
                for widget in number_prop:
                    prop_data["widgets"].append(
                        {
                            "name": getattr(widget, "getName", lambda: "Unknown")(),
                            "label": getattr(
                                widget,
                                "getLabel",
                                lambda: getattr(widget, "getName", lambda: "Unknown")(),
                            )(),
                            "value": getattr(widget, "getValue", lambda: 0.0)(),
                            "min": getattr(widget, "getMin", lambda: 0.0)(),
                            "max": getattr(widget, "getMax", lambda: 0.0)(),
                            "step": getattr(widget, "getStep", lambda: 0.0)(),
                            "format": getattr(widget, "getFormat", lambda: "%g")(),
                        }
                    )

            elif prop.getType() == PyIndi.INDI_SWITCH:
                switch_prop = PyIndi.PropertySwitch(prop)
                for widget in switch_prop:
                    prop_data["widgets"].append(
                        {
                            "name": getattr(widget, "getName", lambda: "Unknown")(),
                            "label": getattr(
                                widget,
                                "getLabel",
                                lambda: getattr(widget, "getName", lambda: "Unknown")(),
                            )(),
                            "state": getattr(
                                widget, "getStateAsString", lambda: "Unknown"
                            )(),
                        }
                    )

            elif prop.getType() == PyIndi.INDI_LIGHT:
                light_prop = PyIndi.PropertyLight(prop)
                for widget in light_prop:
                    prop_data["widgets"].append(
                        {
                            "name": getattr(widget, "getName", lambda: "Unknown")(),
                            "label": getattr(
                                widget,
                                "getLabel",
                                lambda: getattr(widget, "getName", lambda: "Unknown")(),
                            )(),
                            "state": getattr(
                                widget, "getStateAsString", lambda: "Unknown"
                            )(),
                        }
                    )

            elif prop.getType() == PyIndi.INDI_BLOB:
                blob_prop = PyIndi.PropertyBlob(prop)
                for widget in blob_prop:
                    prop_data["widgets"].append(
                        {
                            "name": getattr(widget, "getName", lambda: "Unknown")(),
                            "label": getattr(
                                widget,
                                "getLabel",
                                lambda: getattr(widget, "getName", lambda: "Unknown")(),
                            )(),
                            "format": getattr(widget, "getFormat", lambda: "")(),
                            "size": getattr(widget, "getSize", lambda: 0)(),
                            # Note: We don't record actual blob data to keep file manageable
                            "has_data": getattr(widget, "getSize", lambda: 0)() > 0,
                        }
                    )
        except Exception as e:
            self.logger.warning(
                f"Failed to extract widget data for property {prop.getName()}: {e}"
            )
            # Add minimal widget info if extraction fails
            prop_data["widgets"] = [
                {"name": "unknown", "label": "Failed to extract", "value": "error"}
            ]

        return prop_data

    def newDevice(self, device):
        """Called when a new device is detected."""
        self._write_event(
            "new_device",
            {
                "device_name": device.getDeviceName(),
                "driver_name": device.getDriverName(),
                "driver_exec": device.getDriverExec(),
                "driver_version": device.getDriverVersion(),
            },
        )
        self.logger.info(f"New device: {device.getDeviceName()}")

    def removeDevice(self, device):
        """Called when a device is removed."""
        self._write_event("remove_device", {"device_name": device.getDeviceName()})
        self.logger.info(f"Device removed: {device.getDeviceName()}")

    def newProperty(self, prop):
        """Called when a new property is created."""
        prop_data = self._extract_property_data(prop)
        self._write_event("new_property", prop_data)
        self.logger.info(f"New property: {prop.getName()} on {prop.getDeviceName()}")

    def updateProperty(self, prop):
        """Called when a property value is updated."""
        prop_data = self._extract_property_data(prop)
        self._write_event("update_property", prop_data)
        self.logger.debug(
            f"Property updated: {prop.getName()} on {prop.getDeviceName()}"
        )

    def removeProperty(self, prop):
        """Called when a property is deleted."""
        self._write_event(
            "remove_property",
            {
                "name": prop.getName(),
                "device_name": prop.getDeviceName(),
                "type": prop.getTypeAsString(),
            },
        )
        self.logger.info(
            f"Property removed: {prop.getName()} on {prop.getDeviceName()}"
        )

    def newMessage(self, device, message):
        """Called when a new message arrives from a device."""
        self._write_event(
            "new_message", {"device_name": device.getDeviceName(), "message": message}
        )
        self.logger.info(f"Message from {device.getDeviceName()}: {message}")

    def serverConnected(self):
        """Called when connected to the server."""
        self._write_event(
            "server_connected", {"host": self.getHost(), "port": self.getPort()}
        )
        self.logger.info(
            f"Connected to INDI server at {self.getHost()}:{self.getPort()}"
        )

    def serverDisconnected(self, code):
        """Called when disconnected from the server."""
        self._write_event(
            "server_disconnected",
            {"host": self.getHost(), "port": self.getPort(), "exit_code": code},
        )
        self.logger.info(f"Disconnected from server (exit code: {code})")

    def close(self):
        """Close the output file and clean up resources."""
        if hasattr(self, "file_handle"):
            self.file_handle.close()
            self.logger.info(
                f"Recorded {self.event_count} events to {self.output_file}"
            )


def main():
    """Main function to run the event recorder."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Record INDI server events to JSON file"
    )
    parser.add_argument("--host", default="localhost", help="INDI server host")
    parser.add_argument("--port", type=int, default=7624, help="INDI server port")
    parser.add_argument(
        "--output",
        default="indi_events.jsonl",
        help="Output file for events (optional, default: indi_events.jsonl)",
    )
    parser.add_argument("--duration", type=int, help="Recording duration in seconds")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=log_level
    )

    logger = logging.getLogger("main")

    # Create and configure recorder
    recorder = IndiEventRecorder(args.output)
    recorder.setServer(args.host, args.port)

    try:
        # Connect to server
        logger.info(f"Connecting to INDI server at {args.host}:{args.port}")
        if not recorder.connectServer():
            logger.error(f"Failed to connect to INDI server at {args.host}:{args.port}")
            logger.error("Make sure the INDI server is running, e.g.:")
            logger.error("  indiserver indi_simulator_telescope indi_simulator_ccd")
            sys.exit(1)

        logger.info("Recording events... Press Ctrl+C to stop")

        # Record for specified duration or until interrupted
        start_time = time.time()
        while True:
            time.sleep(0.1)  # Small sleep to prevent busy loop

            if args.duration and (time.time() - start_time) >= args.duration:
                logger.info(f"Recording completed after {args.duration} seconds")
                break

    except KeyboardInterrupt:
        logger.info("Recording stopped by user")
    except Exception as e:
        logger.error(f"Error during recording: {e}")
    finally:
        recorder.disconnectServer()
        recorder.close()


if __name__ == "__main__":
    main()
