"""Pairwise interaction grids for the SSD1333 (separability test).

Six axis-pair 4x4 grids, others pinned at reference, plus the
policy-critical dim-regime slice: contrast x pre-charge at ceiling 4,
master 0 — the surface the dimming policy's pre-charge regime actually
walks. One rig session, per-grid journals, sentinels every 10 points.
"""

import json
import sys
import time

sys.path.insert(0, "/home/pifinder/PiFinder/python")

from PiFinder.panel_photometry import MEASUREMENTS_DIR, Rig, run_sweep

OUT_DIR = MEASUREMENTS_DIR / "ssd1333"

GRID = {
    "contrast": [4, 16, 64, 160],
    "master": [0, 3, 7, 15],
    "ceiling": [2, 4, 10, 31],
    "precharge": [0, 8, 16, 23],
}

PAIRS = [
    ("contrast", "master"),
    ("contrast", "ceiling"),
    ("contrast", "precharge"),
    ("master", "ceiling"),
    ("master", "precharge"),
    ("ceiling", "precharge"),
]


def pair_spec(a, b):
    return {
        "description": f"4x4 interaction grid: {a} x {b}, others at reference",
        "pinned": {},
        "sentinel_every": 10,
        "points": [
            {"axes": {a: va, b: vb}, "value": 255}
            for va in GRID[a]
            for vb in GRID[b]
        ],
    }


DIM_SLICE = {
    "description": "dim-regime policy slice: contrast x precharge at ceiling 4, master 0",
    "pinned": {"ceiling": 4, "master": 0},
    "sentinel_every": 10,
    "points": [
        {"axes": {"contrast": c, "precharge": p}, "value": 255}
        for c in [1, 2, 4, 8, 16]
        for p in [6, 8, 12, 16, 23]
    ],
}


def main():
    runs = [(pair_spec(a, b), f"grid-{a}-{b}-20260802.jsonl") for a, b in PAIRS]
    runs.append((DIM_SLICE, "dimslice-contrast-precharge-20260802.jsonl"))

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
    print("\nall grids complete")


if __name__ == "__main__":
    main()
