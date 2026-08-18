"""APL / current-limiting probe for the SSD1333.

Hypothesis: the compressed axis responses measured with a full-screen
value-255 frame are load compression (global current limiting at high
average picture level), not the axes' true response. Discriminator: the
contrast response ratio flux(64)/flux(4) should steepen toward the
multiplicative model's 16x as the lit fraction falls, and flux per lit
pixel at fixed axes should rise as fill drops.

Patterns: full fill, 1-in-4 (every other row+col), 1-in-16 (one pixel per
4x4 block). Ceiling stays 31 (render LUT is a pass-through) so drawing
directly to the device bypasses nothing.
"""

import sys
import time

sys.path.insert(0, "/home/pifinder/PiFinder/python")

from PIL import Image
from PiFinder.panel_photometry import Rig, SETTLE_SECONDS

JOURNAL = (
    "/home/pifinder/PiFinder/docs/ax/display/measurements/ssd1333/"
    "apl-fill-probe-20260802.jsonl"
)

FILLS = {"1/1": 1, "1/4": 2, "1/16": 4}  # name -> block stride
CONTRASTS = [4, 16, 64, 160]
MASTERS = [7, 15]  # master checked at contrast 64 only


def pattern(resolution, stride, value):
    img = Image.new("RGB", resolution, (0, 0, 0))
    px = img.load()
    for y in range(0, resolution[1], stride):
        for x in range(0, resolution[0], stride):
            px[x, y] = (value, 0, 0)
    return img


def show(panel, stride, value=255):
    img = pattern(panel.display.resolution, stride, value)
    panel.display.device.display(img.convert(panel.display.device.mode))


def measure_pattern(rig, axes, stride, label):
    rig.panel.set_state(axes, 0)  # programs axes, blanks
    show(rig.panel, stride)
    time.sleep(SETTLE_SECONDS)
    result = rig.photometer.measure()
    rig._seq += 1
    record = {
        "type": "apl_probe",
        "seq": rig._seq,
        "time": time.time(),
        "panel": rig.panel_name,
        "state": dict(rig.panel.state(), fill=label, value=255),
        **result,
    }
    rig.journal(record)
    flux = result["flux"]
    print(f"fill {label:>4} stride axes={axes}: "
          f"{flux:.4g} ADU/s (tier {result['tier_us']}us)"
          if flux is not None else f"fill {label} {axes}: SATURATED")
    return record


def main():
    with Rig("ssd1333", journal_path=JOURNAL) as rig:
        # Warm the panel: full-screen reference state for 90 s so the
        # sentinel-visible warm-up transient is behind us.
        rig.panel.set_state({}, 255)
        print("warming panel 90s at reference...")
        time.sleep(90)
        rig.measure_sentinel()

        # Interleave fills within each contrast so slow drift cancels in
        # the per-fill ratios.
        for contrast in CONTRASTS:
            for label, stride in FILLS.items():
                measure_pattern(
                    rig, {"contrast": contrast, "master": 7}, stride, label
                )
        for master in MASTERS:
            for label, stride in FILLS.items():
                measure_pattern(
                    rig, {"contrast": 64, "master": master}, stride, label
                )
        rig.measure_sentinel()
    print("done:", JOURNAL)


if __name__ == "__main__":
    main()
