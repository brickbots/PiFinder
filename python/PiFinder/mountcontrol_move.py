#!/usr/bin/env python3
"""
INDI Telescope Commander

A tool for commanding sequential telescope movements via INDI server.
Supports arbitrary slews in RA/Dec with configurable velocity.

Usage:
    python telescope_commander.py --moves "+15RA,-10DEC" "+5DEC" --velocity 4 --device "Telescope Simulator"
    python telescope_commander.py -m "+1RA" -m "-2DEC,+3RA" -v 2
"""

import argparse
import sys
import time
from typing import List, Tuple, Optional
from dataclasses import dataclass

try:
    import PyIndi
except ImportError:
    print("Error: PyIndi library not found.")
    print("Install with: pip install pyindi-client")
    sys.exit(1)

from PiFinder.mountcontrol_indi import PiFinderIndiClient


@dataclass
class Movement:
    """Represents a single movement command"""

    ra_offset: float = 0.0  # degrees
    dec_offset: float = 0.0  # degrees
    velocity: int = 2  # velocity index (default)

    def __str__(self):
        parts = []
        if self.ra_offset != 0:
            parts.append(f"{self.ra_offset:+.2f}° RA")
        if self.dec_offset != 0:
            parts.append(f"{self.dec_offset:+.2f}° Dec")
        movement_str = ", ".join(parts) if parts else "No movement"
        return f"{movement_str} @ velocity {self.velocity}"


class TelescopeCommander:
    """Commands telescope movements via INDI"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 7624,
        device_name: str = "Telescope Simulator",
    ):
        self.host = host
        self.port = port
        self.device_name = device_name
        # Use PiFinderIndiClient from mountcontrol_indi
        # Pass None as mount_control since we don't need the position update callbacks
        self.client = PiFinderIndiClient(mount_control=None)
        self.device: PyIndi.BaseDevice = None
        self.available_slew_rates: Optional[List[str]] = None

    def connect(self) -> bool:
        """Connect to INDI server and telescope device"""
        print(f"Connecting to INDI server at {self.host}:{self.port}...")

        self.client.setServer(self.host, self.port)

        if not self.client.connectServer():
            print(f"Error: Could not connect to INDI server at {self.host}:{self.port}")
            print(
                "Make sure indiserver is running (e.g., 'indiserver indi_simulator_telescope')"
            )
            return False

        print("Connected to INDI server")

        # Wait for device to be available (telescope_device is auto-detected)
        timeout = 10
        start = time.time()
        while time.time() - start < timeout:
            self.device = self.client.get_telescope_device()
            if self.device:
                break
            time.sleep(0.5)

        if not self.device:
            print("Error: No telescope device found")
            print("Available devices:")
            for dev in self.client.getDevices():
                print(f"  - {dev.getDeviceName()}")
            return False

        print(f"Found device: {self.device.getDeviceName()}")

        # Connect to device if not already connected
        if not self.device.isConnected():
            print(f"Connecting to device {self.device.getDeviceName()}...")
            if not self.client.set_switch(self.device, "CONNECTION", "CONNECT"):
                print("Error: Could not connect to device")
                return False

            # Wait for connection
            timeout = 10
            start = time.time()
            while time.time() - start < timeout:
                if self.device.isConnected():
                    break
                time.sleep(0.5)

            if not self.device.isConnected():
                print("Error: Could not connect to device")
                return False

        print(f"Device {self.device.getDeviceName()} connected")

        # Read and store available slew rates
        self.available_slew_rates = self.get_available_slew_rates()
        if self.available_slew_rates:
            print(
                f"Available slew rates: {len(self.available_slew_rates)} rates detected"
            )

        return True

    def get_available_slew_rates(self) -> Optional[List[str]]:
        """
        Get available slew rates from the telescope device

        Returns:
            List of slew rate names, or None if property not available
        """
        slew_rate_prop = self.client._wait_for_property(
            self.device, "TELESCOPE_SLEW_RATE", timeout=2.0
        )
        if not slew_rate_prop:
            return None

        slew_rate_switch = self.device.getSwitch("TELESCOPE_SLEW_RATE")
        if not slew_rate_switch:
            return None

        available_rates = []
        for i in range(len(slew_rate_switch)):
            widget = slew_rate_switch[i]
            available_rates.append(widget.label if widget.label else widget.name)

        return available_rates

    def set_slew_rate(self, rate: int) -> bool:
        """
        Set telescope slew rate

        Args:
            rate: Slew rate index (0-based index into available slew rates)

        Returns:
            True if rate was set successfully, False otherwise
        """
        if self.available_slew_rates is None:
            print("Warning: No slew rates available from device")
            return False

        if rate < 0 or rate >= len(self.available_slew_rates):
            print(
                f"Error: Rate {rate} is out of range (0-{len(self.available_slew_rates)-1})"
            )
            return False

        # Get the actual switch property to find element names
        slew_rate_switch = self.device.getSwitch("TELESCOPE_SLEW_RATE")
        if not slew_rate_switch:
            print("Warning: TELESCOPE_SLEW_RATE property not found")
            return False

        # Get the element name at the specified index
        rate_element_name = slew_rate_switch[rate].name
        rate_label = self.available_slew_rates[rate]

        print(f"Setting slew rate to: {rate_label} (level {rate})")

        if not self.client.set_switch(
            self.device, "TELESCOPE_SLEW_RATE", rate_element_name
        ):
            print("Warning: Could not set slew rate")
            return False

        time.sleep(0.5)
        return True

    def get_current_position(self) -> Optional[Tuple[float, float]]:
        """Get current telescope RA/Dec position in hours and degrees"""
        # Wait for property to be available
        equatorial_prop = self.client._wait_for_property(
            self.device, "EQUATORIAL_EOD_COORD", timeout=2.0
        )
        if not equatorial_prop:
            return None

        equatorial = self.device.getNumber("EQUATORIAL_EOD_COORD")
        if not equatorial:
            return None

        ra = equatorial[0].value  # Hours
        dec = equatorial[1].value  # Degrees

        return (ra, dec)

    def get_horizontal_position(self) -> Optional[Tuple[float, float]]:
        """Get current telescope Alt/Az position in degrees

        Returns:
            Tuple of (altitude, azimuth) in degrees, or None if not available
        """
        # Wait for property to be available
        horizontal_prop = self.client._wait_for_property(
            self.device, "HORIZONTAL_COORD", timeout=2.0
        )
        if not horizontal_prop:
            return None

        horizontal = self.device.getNumber("HORIZONTAL_COORD")
        if not horizontal:
            return None

        # INDI HORIZONTAL_COORD has ALT and AZ elements
        alt = None
        az = None
        for i in range(len(horizontal)):
            if horizontal[i].name == "ALT":
                alt = horizontal[i].value
            elif horizontal[i].name == "AZ":
                az = horizontal[i].value

        if alt is not None and az is not None:
            return (alt, az)

        return None

    def slew_relative(self, ra_offset_deg: float, dec_offset_deg: float) -> bool:
        """
        Slew telescope by relative offsets

        Args:
            ra_offset_deg: RA offset in degrees
            dec_offset_deg: Dec offset in degrees
        """
        # Get current position
        current = self.get_current_position()
        if not current:
            print("Error: Could not get current position")
            return False

        current_ra_hours, current_dec_deg = current
        current_ra_deg = current_ra_hours * 15.0  # Convert hours to degrees

        # Calculate target position
        target_ra_deg = current_ra_deg + ra_offset_deg
        target_dec_deg = current_dec_deg + dec_offset_deg

        # Normalize RA to 0-360
        target_ra_deg = target_ra_deg % 360.0
        target_ra_hours = target_ra_deg / 15.0

        # Clamp Dec to -90 to +90
        target_dec_deg = max(-90.0, min(90.0, target_dec_deg))

        print(
            f"  Current: RA={current_ra_hours:.4f}h ({current_ra_deg:.2f}°), Dec={current_dec_deg:.2f}°"
        )
        print(
            f"  Target:  RA={target_ra_hours:.4f}h ({target_ra_deg:.2f}°), Dec={target_dec_deg:.2f}°"
        )

        # Set ON_COORD_SET to TRACK mode (goto and track)
        if not self.client.set_switch(self.device, "ON_COORD_SET", "TRACK"):
            print("Error: Failed to set ON_COORD_SET to TRACK")
            return False

        # Set target coordinates using the helper method
        if not self.client.set_number(
            self.device,
            "EQUATORIAL_EOD_COORD",
            {"RA": target_ra_hours, "DEC": target_dec_deg},
        ):
            print("Error: Failed to set goto coordinates")
            return False

        # Wait for slew to complete
        print("  Slewing", end="", flush=True)
        timeout = 60
        start = time.time()

        equatorial = self.device.getNumber("EQUATORIAL_EOD_COORD")
        if not equatorial:
            print(" Error: Could not get EQUATORIAL_EOD_COORD property")
            return False

        i = 0
        while time.time() - start < timeout:
            state = equatorial.getState()
            if state == PyIndi.IPS_OK:
                print(" Complete!")
                return True
            elif state == PyIndi.IPS_ALERT:
                print(" Failed!")
                return False
            time.sleep(0.2)
            i += 1
            if i % 5 == 0:
                print(".", end="", flush=True)
                i = 0

        print(" Timeout!")
        return False

    def execute_movements(
        self, movements: List[Movement], print_horizontal: bool = False
    ) -> bool:
        """
        Execute a sequence of movements

        Args:
            movements: List of Movement objects (each with its own velocity)
            print_horizontal: If True, print horizontal coordinates (Alt/Az) before and after each movement

        Returns:
            True if all movements succeeded, False otherwise
        """
        total = len(movements)
        success_count = 0

        for i, movement in enumerate(movements, 1):
            print(f"\n[Step {i}/{total}] Executing: {movement}")

            if movement.ra_offset == 0 and movement.dec_offset == 0:
                print("  Skipping: No movement specified")
                success_count += 1
                continue

            # Print start horizontal coordinates if requested
            if print_horizontal:
                start_horizontal = self.get_horizontal_position()
                if start_horizontal:
                    alt_start, az_start = start_horizontal
                    print(f"  Start Alt/Az: Alt={alt_start:.2f}°, Az={az_start:.2f}°")
                else:
                    print("  Start Alt/Az: Not available")

            # Set slew rate for this specific movement
            if not self.set_slew_rate(movement.velocity):
                print("Warning: Could not set slew rate, continuing with current rate")

            if self.slew_relative(movement.ra_offset, movement.dec_offset):
                # Print end horizontal coordinates if requested
                if print_horizontal:
                    end_horizontal = self.get_horizontal_position()
                    if end_horizontal:
                        alt_end, az_end = end_horizontal
                        print(f"  End Alt/Az:   Alt={alt_end:.2f}°, Az={az_end:.2f}°")
                    else:
                        print("  End Alt/Az: Not available")

                success_count += 1
            else:
                print(f"  Failed to execute step {i}")

        print(f"\n{'='*60}")
        print(f"Completed {success_count}/{total} movements successfully")
        return success_count == total

    def disconnect(self):
        """Disconnect from INDI server"""
        if self.client:
            self.client.disconnectServer()
            print("Disconnected from INDI server")


def parse_movement(move_spec: str) -> Movement:
    """
    Parse a movement specification string

    Format: "+15RA,-10DEC" or "+5DEC" or "-3RA,+2DEC"

    Args:
        move_spec: Movement specification string

    Returns:
        Movement object
    """
    movement = Movement()

    # Split by comma to get individual axis movements
    parts = move_spec.upper().replace(" ", "").split(",")

    for part in parts:
        if not part:
            continue

        # Extract axis (RA or DEC)
        if "RA" in part:
            axis = "RA"
            value_str = part.replace("RA", "")
        elif "DEC" in part:
            axis = "DEC"
            value_str = part.replace("DEC", "")
        else:
            print(f"Warning: Unknown axis in '{part}', skipping")
            continue

        # Parse value
        try:
            value = float(value_str)
        except ValueError:
            print(f"Warning: Invalid value in '{part}', skipping")
            continue

        # Set the appropriate offset
        if axis == "RA":
            movement.ra_offset = value
        elif axis == "DEC":
            movement.dec_offset = value

    return movement


def main():
    # First, manually parse -v and -m flags to handle interleaving
    # before argparse processes them
    movements_with_velocities = []
    current_velocity = 2  # default velocity

    # Filter out -v and -m args for manual processing
    filtered_argv = ["mountcontrol_move.py"]  # Start with program name
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]

        if arg in ["-v", "--velocity"]:
            # Next arg should be the velocity value
            if i + 1 < len(sys.argv):
                try:
                    current_velocity = int(sys.argv[i + 1])
                    i += 2
                    continue
                except ValueError:
                    print(f"Error: Invalid velocity value '{sys.argv[i + 1]}'")
                    return 1
            else:
                print("Error: -v/--velocity requires a value")
                return 1
        elif arg in ["-m", "--moves"]:
            # Next arg should be the movement spec
            if i + 1 < len(sys.argv):
                move_spec = sys.argv[i + 1]
                movements_with_velocities.append((move_spec, current_velocity))
                i += 2
                continue
            else:
                print("Error: -m/--moves requires a value")
                return 1
        else:
            # Pass through other arguments to argparse
            filtered_argv.append(arg)
            i += 1

    parser = argparse.ArgumentParser(
        description="Command telescope movements via INDI server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single movement: +15° RA, -10° Dec at velocity 4 (old style)
  %(prog)s --moves "+15RA,-10DEC" --velocity 4

  # Multiple movements with interleaved velocities (new style)
  %(prog)s -v 3 -m "+10RA" -v 0 -m "-10RA"

  # Multiple movements in sequence at same velocity
  %(prog)s -v 2 -m "+15RA,-10DEC" -m "+5DEC" -m "-20RA"

  # Use a specific device
  %(prog)s -v 2 -m "+10RA" -d "LX200 GPS"

  # Connect to remote INDI server
  %(prog)s -m "+5DEC" --host 192.168.1.100 --port 7624

Velocity levels:
  Velocity indices are device-specific (typically 0-3).
  Use --list-velocities to see available rates for your device.
  Common levels: 0=Guide (slowest), 1=Centering, 2=Find, 3=Max (fastest)

  The -v flag applies to all following -m flags until another -v is specified.
        """,
    )

    parser.add_argument(
        "--list-velocities",
        action="store_true",
        help="Connect to device and list available slew velocities, then exit",
    )

    parser.add_argument(
        "-p",
        "--print-horizontal",
        action="store_true",
        help="Print horizontal coordinates (Alt/Az) for start and end of each movement",
    )

    parser.add_argument(
        "-d",
        "--device",
        default="Telescope Simulator",
        help="INDI device name. Default: 'Telescope Simulator'",
    )

    parser.add_argument(
        "--host", default="localhost", help="INDI server host. Default: localhost"
    )

    parser.add_argument(
        "--port", type=int, default=7624, help="INDI server port. Default: 7624"
    )

    args = parser.parse_args(filtered_argv[1:])

    # Create commander
    commander = TelescopeCommander(args.host, args.port, args.device)

    try:
        if not commander.connect():
            return 1

        # Handle --list-velocities flag
        if args.list_velocities:
            print("\n" + "=" * 60)
            print("Available Slew Velocities")
            print("=" * 60)
            rates = commander.get_available_slew_rates()
            if rates:
                for i, rate_name in enumerate(rates):
                    print(f"  {i}: {rate_name}")
            else:
                print("  Device does not support TELESCOPE_SLEW_RATE property")
            print()
            return 0

        # Movement mode requires --moves
        if not movements_with_velocities:
            print("Error: --moves (-m) is required for movement commands")
            print("Use --list-velocities to see available slew rates")
            return 1

        # Parse movement specifications and validate velocities
        print("Parsing movement specifications...")
        movements = []
        for move_spec, velocity in movements_with_velocities:
            movement = parse_movement(move_spec)
            movement.velocity = velocity

            # Validate velocity for this movement
            if velocity < 0:
                print(
                    f"Error: Velocity must be non-negative (got {velocity} for movement '{move_spec}')"
                )
                return 1

            if commander.available_slew_rates:
                max_velocity = len(commander.available_slew_rates) - 1
                if velocity > max_velocity:
                    print(
                        f"Error: Velocity {velocity} is out of range for this device (movement '{move_spec}')"
                    )
                    print(f"Available range: 0-{max_velocity}")
                    print("Use --list-velocities to see available slew rates")
                    return 1

            movements.append(movement)
            print(f"  - {movement}")

        if not movements:
            print("Error: No valid movements specified")
            return 1

        print(f"\nTotal movements: {len(movements)}")
        print()

        print("\n" + "=" * 60)
        print("Starting movement sequence")
        print("=" * 60)

        success = commander.execute_movements(
            movements, print_horizontal=args.print_horizontal
        )

        return 0 if success else 1

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        return 130

    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        return 1

    finally:
        commander.disconnect()


if __name__ == "__main__":
    sys.exit(main())
