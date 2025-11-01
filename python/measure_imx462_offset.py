#!/usr/bin/env python3
"""
Measure imx462 black level offset and optimal digital_gain.

Instructions:
1. Part 1: Put lens cap on camera → measures offset
2. Part 2: Point at stars → tests digital_gain values
3. Script reports statistics and recommendations
4. Update camera_pi.py with measured values
"""

import numpy as np
import sys
from pathlib import Path
from typing import Dict, List

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

    return bias_frame


def count_stars_simple(image: np.ndarray, threshold: int = 50) -> int:
    """Simple star counting using thresholding (faster than full centroiding)."""
    from scipy import ndimage

    # Threshold image
    binary = image > threshold

    # Label connected regions
    labeled, num_features = ndimage.label(binary)

    return num_features


def measure_digital_gain(camera: CameraPI, measured_offset: int) -> Dict[float, Dict]:
    """Test different digital_gain values and measure image quality metrics."""

    print("\n" + "="*60)
    print("PART 2: DIGITAL GAIN OPTIMIZATION")
    print("="*60)
    print("\n*** POINT CAMERA AT STARS (remove lens cap) ***")
    print("Ideally point at moderately dense star field")
    input("\nPress Enter when ready...")

    # Test these gain values
    test_gains = [1.0, 3.0, 5.0, 7.0, 10.0, 13.0]
    results = {}

    # Temporarily update offset for testing
    original_offset = camera.offset
    camera.offset = measured_offset

    print(f"\nTesting digital_gain values: {test_gains}")
    print("This will take ~30 seconds...")
    print()

    for gain in test_gains:
        print(f"Testing gain={gain}x...", end=" ", flush=True)

        # Temporarily set digital_gain
        camera.digital_gain = gain

        # Capture processed image
        image = camera.capture()
        img_array = np.array(image)

        # Calculate statistics
        mean = np.mean(img_array)
        median = np.median(img_array)
        p01 = np.percentile(img_array, 1)
        p99 = np.percentile(img_array, 99)
        std = np.std(img_array)

        # Clipping detection
        clipped_low = np.sum(img_array == 0)
        clipped_high = np.sum(img_array == 255)
        total_pixels = img_array.size
        clip_pct = (clipped_low + clipped_high) / total_pixels * 100

        # Dynamic range (usable range between p01 and p99)
        dynamic_range = p99 - p01

        # Count stars (simple thresholding)
        star_count = count_stars_simple(img_array, threshold=int(mean + 2*std))

        results[gain] = {
            'mean': mean,
            'median': median,
            'p01': p01,
            'p99': p99,
            'std': std,
            'dynamic_range': dynamic_range,
            'clip_pct': clip_pct,
            'star_count': star_count,
        }

        print(f"✓ (mean={mean:.1f}, stars={star_count}, clip={clip_pct:.1f}%)")

    # Restore original settings
    camera.offset = original_offset
    camera.digital_gain = 1.0

    return results


def display_gain_comparison(results: Dict[float, Dict]):
    """Display comparison table of digital_gain test results."""

    print("\n" + "="*60)
    print("DIGITAL GAIN COMPARISON")
    print("="*60)
    print(f"{'Gain':>5} {'Mean':>6} {'p01':>5} {'p99':>5} {'Range':>6} {'Stars':>6} {'Clip%':>6}")
    print("-"*60)

    for gain in sorted(results.keys()):
        r = results[gain]
        print(f"{gain:>5.1f}x {r['mean']:>6.1f} {r['p01']:>5.0f} {r['p99']:>5.0f} "
              f"{r['dynamic_range']:>6.0f} {r['star_count']:>6} {r['clip_pct']:>6.2f}")

    print("="*60)
    print("\nColumn descriptions:")
    print("  Gain  = Digital gain multiplier")
    print("  Mean  = Average brightness (higher = brighter)")
    print("  p01   = 1st percentile (should be >0 to avoid black clipping)")
    print("  p99   = 99th percentile (should be <255 to avoid white clipping)")
    print("  Range = Dynamic range (p99 - p01, higher = better)")
    print("  Stars = Detected centroids (more = better for solving)")
    print("  Clip% = Percentage of clipped pixels (lower = better)")

    # Recommendations
    print("\n" + "="*60)
    print("RECOMMENDATIONS:")
    print("="*60)

    # Find gain with max stars and minimal clipping
    best_stars = max(results.items(), key=lambda x: x[1]['star_count'])
    best_range = max(results.items(), key=lambda x: x[1]['dynamic_range'])
    min_clip = min(results.items(), key=lambda x: x[1]['clip_pct'])

    print(f"\n📊 Best star count:     {best_stars[0]}x ({best_stars[1]['star_count']} stars)")
    print(f"📊 Best dynamic range:  {best_range[0]}x ({best_range[1]['dynamic_range']:.0f} levels)")
    print(f"📊 Minimal clipping:    {min_clip[0]}x ({min_clip[1]['clip_pct']:.2f}%)")

    # HQ camera reference
    hq_ref_gain = 13.0
    if hq_ref_gain in results:
        print(f"\n📷 HQ camera reference: {hq_ref_gain}x (mean={results[hq_ref_gain]['mean']:.1f})")

    print("\n💡 Suggested digital_gain: 5.0-10.0 (good balance)")
    print("   • Lower gain (3-5x): Less noise, may lose faint stars")
    print("   • Medium gain (7-10x): Balanced, good for most conditions")
    print("   • Higher gain (13x): Maximum sensitivity, may be noisy")


if __name__ == "__main__":
    try:
        # Part 1: Measure offset
        print("="*60)
        print("IMX462 CAMERA CALIBRATION")
        print("="*60)

        offset = measure_offset()

        # Part 2: Measure digital_gain
        print("\n\nWould you like to test digital_gain values? (requires stars)")
        response = input("Continue with gain testing? (y/n): ")

        if response.lower() == 'y':
            # Reinitialize camera for gain testing
            print("\nReinitializing camera...")
            camera = CameraPI(exposure_time=100000)

            # Use measured offset
            recommended_offset = int(round(np.mean(offset))) if isinstance(offset, np.ndarray) else 256

            results = measure_digital_gain(camera, recommended_offset)
            display_gain_comparison(results)

        print("\n✅ Calibration complete!")

    except KeyboardInterrupt:
        print("\n\nMeasurement cancelled.")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
