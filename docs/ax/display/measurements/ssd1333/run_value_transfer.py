"""Pixel-value transfer sweeps for the SSD1333.

Full-screen uniform frames at every native gray level (pixel value =
8 x level, levels 1-31) plus 0 and 255, at four operating points spanning
the dimming range. Tests the "level n emits proportional to n-1" law and the
emitted-light-space ceiling remap; the value-64 vs value-255 ratio at each
operating point is the tonal-range deliverable.
"""

import sys
import time

sys.path.insert(0, "/home/pifinder/PiFinder/python")

from PiFinder.panel_photometry import MEASUREMENTS_DIR, Rig, run_sweep

OUT_DIR = MEASUREMENTS_DIR / "ssd1333"

VALUES = [0] + [8 * level for level in range(1, 32)] + [255]

OPERATING_POINTS = [
    ("bright-ref", {"contrast": 64, "master": 7, "ceiling": 31, "precharge": 23}),
    ("mid-drive", {"contrast": 16, "master": 3, "ceiling": 31, "precharge": 23}),
    ("knee", {"contrast": 4, "master": 0, "ceiling": 4, "precharge": 23}),
    ("dimmest", {"contrast": 4, "master": 0, "ceiling": 4, "precharge": 8}),
]


def main():
    runs = [
        (
            {
                "description": f"pixel-value transfer at {name}: {axes}",
                "pinned": axes,
                "sentinel_every": 12,
                "points": [{"axes": {}, "value": v} for v in VALUES],
            },
            f"valuetransfer-{name}-20260802.jsonl",
        )
        for name, axes in OPERATING_POINTS
    ]

    first_journal = OUT_DIR / runs[0][1]
    with Rig("ssd1333", journal_path=first_journal) as rig:
        rig_record = {
            "type": "rig",
            "camera": rig.photometer.camera_type,
            "refresh_us": rig.photometer.refresh_us,
            "tiers_us": rig.photometer.tiers_us,
            "tier_scale": {str(k): v for k, v in rig.photometer.tier_scale.items()},
        }
        rig.panel.set_state({}, 255)
        print("warming panel 90s at reference...")
        time.sleep(90)

        for spec, journal_name in runs:
            rig.journal_path = OUT_DIR / journal_name
            if rig.journal_path != first_journal:
                rig.journal(rig_record)
            print(f"\n=== {spec['description']} -> {journal_name} ===")
            run_sweep(rig, spec, set())
    print("\nall value-transfer sweeps complete")


if __name__ == "__main__":
    main()
