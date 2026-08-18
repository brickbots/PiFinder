"""Boundary hunts for the SSD1333.

1. Pre-charge cut-out edge in the dim regime (ceiling 4, master 0,
   contrast 4) — the state just above the edge is the policy's candidate
   emission floor.
2. Pre-charge edge at ceiling 2, both weak and strong drive (the
   ceiling x precharge grid showed ceiling 2 + pc 0 dark even at
   contrast 64 / master 7).
3. Joint contrast x master cut-out boundary at full ceiling, and again in
   the dim regime (the 1-D sweeps showed contrast 1 lit at master 7 but
   dark at master 0 — the cut-out is a joint boundary, not per-axis).

Spatial artifacts stay eyeball-judged; this only maps where light stops.
"""

import json
import sys
import time

sys.path.insert(0, "/home/pifinder/PiFinder/python")

from PiFinder.panel_photometry import MEASUREMENTS_DIR, Rig, run_sweep

OUT_DIR = MEASUREMENTS_DIR / "ssd1333"

RUNS = [
    (
        {
            "description": "precharge cut-out edge, dim regime (c4 m0 L4)",
            "pinned": {"contrast": 4, "master": 0, "ceiling": 4},
            "sentinel_every": 10,
            "points": [{"axes": {"precharge": p}, "value": 255} for p in range(0, 9)],
        },
        "edge-precharge-dimregime-20260802.jsonl",
    ),
    (
        {
            "description": "precharge edge at ceiling 2, weak drive (c4 m0)",
            "pinned": {"contrast": 4, "master": 0, "ceiling": 2},
            "sentinel_every": 12,
            "points": [{"axes": {"precharge": p}, "value": 255} for p in range(0, 11)],
        },
        "edge-precharge-ceiling2-weak-20260802.jsonl",
    ),
    (
        {
            "description": "precharge edge at ceiling 2, reference drive (c64 m7)",
            "pinned": {"contrast": 64, "master": 7, "ceiling": 2},
            "sentinel_every": 12,
            "points": [{"axes": {"precharge": p}, "value": 255} for p in range(0, 9)],
        },
        "edge-precharge-ceiling2-ref-20260802.jsonl",
    ),
    (
        {
            "description": "contrast x master joint cut-out, full ceiling",
            "pinned": {"ceiling": 31, "precharge": 23},
            "sentinel_every": 10,
            "points": [
                {"axes": {"contrast": c, "master": m}, "value": 255}
                for c in [1, 2, 3, 4]
                for m in [0, 1, 2, 3]
            ],
        },
        "edge-drive-cutout-L31-20260802.jsonl",
    ),
    (
        {
            "description": "contrast x master joint cut-out, dim regime (L4 pc23)",
            "pinned": {"ceiling": 4, "precharge": 23},
            "sentinel_every": 10,
            "points": [
                {"axes": {"contrast": c, "master": m}, "value": 255}
                for c in [1, 2, 3, 4]
                for m in [0, 1, 2]
            ],
        },
        "edge-drive-cutout-L4-20260802.jsonl",
    ),
]


def main():
    first_journal = OUT_DIR / RUNS[0][1]
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

        for spec, journal_name in RUNS:
            rig.journal_path = OUT_DIR / journal_name
            if rig.journal_path != first_journal:
                rig.journal(rig_record)
            print(f"\n=== {spec['description']} -> {journal_name} ===")
            run_sweep(rig, spec, set())
    print("\nall boundary hunts complete")


if __name__ == "__main__":
    main()
