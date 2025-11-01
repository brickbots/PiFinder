#!/usr/bin/env python3
"""
Measure imx462 black level offset.

Instructions:
1. Put lens cap on camera
2. Run this script: python3 measure_imx462_offset.py
3. Script will capture bias frame and report statistics
4. Update camera_pi.py line ~50 with measured offset value
"""

import numpy as np
import sys
from pathlib import Path

# Add PiFinder to path
sys.path.insert(0, str(Path(__file__).parent))

from PiFinder.camera_pi import CameraPI


def measure_offset():
    """Measure camera black level offset with lens cap on."""

    print("Initializing imx462 camera...")
    print("*** MAKE SURE LENS CAP IS ON! ***\n")
    input("Press Enter when ready...")

    # Initialize camera with default exposure
    camera = CameraPI(exposure_time=100000)  # 100ms default

    print(f"\nDetected camera: {camera.camera_type}")

    if camera.camera_type != "imx462":
        print(f"\nWARNING: Expected imx462 but got {camera.camera_type}")
        print("This script is designed for imx462 offset measurement.")
        response = input("Continue anyway? (y/n): ")
        if response.lower() != 'y':
            return

    print("\nCapturing bias frame (0µs exposure)...")
    bias_frame = camera.capture_bias()

    print(f"\nBias frame shape: {bias_frame.shape}")
    print(f"Data type: {bias_frame.dtype}")
    print(f"Bit depth: {camera.bit_depth}-bit")

    # Calculate statistics
    mean = np.mean(bias_frame)
    median = np.median(bias_frame)
    std = np.std(bias_frame)
    min_val = np.min(bias_frame)
    max_val = np.max(bias_frame)

    print("\n" + "="*60)
    print("BIAS FRAME STATISTICS:")
    print("="*60)
    print(f"Mean:      {mean:.2f} ADU")
    print(f"Median:    {median:.2f} ADU")
    print(f"Std Dev:   {std:.2f} ADU")
    print(f"Min:       {min_val} ADU")
    print(f"Max:       {max_val} ADU")
    print("="*60)

    # Recommendation
    recommended_offset = int(round(mean))

    print(f"\nRECOMMENDED OFFSET: {recommended_offset} ADU")
    print(f"\nUpdate camera_pi.py around line 50:")
    print(f"    elif \"imx290\" in self.camera.camera.id:")
    print(f"        self.camera_type = \"imx462\"")
    print(f"        self.raw_size = (1920, 1080)")
    print(f"        self.gain = 30")
    print(f"        self.offset = {recommended_offset}  # Measured {np.datetime64('today')}")
    print(f"        # Remove default offset=0 from line 35")

    # Save bias frame for inspection
    output_file = "bias_imx462.npy"
    np.save(output_file, bias_frame)
    print(f"\nBias frame saved to: {output_file}")
    print("(Load with: np.load('bias_imx462.npy'))")


if __name__ == "__main__":
    try:
        measure_offset()
    except KeyboardInterrupt:
        print("\n\nMeasurement cancelled.")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
