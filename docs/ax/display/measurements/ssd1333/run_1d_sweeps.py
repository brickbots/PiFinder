"""All four SSD1333 1-D axis sweeps in one rig session.

One bring-up, one 90 s warm-up, then contrast / master / ceiling /
pre-charge specs back-to-back, each journaling to its own file. The rig
and ladder calibration records are re-journaled into every file so each
journal is self-contained for analysis.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/pifinder/PiFinder/python")

from PiFinder.panel_photometry import MEASUREMENTS_DIR, Rig, run_sweep

SPEC_DIR = Path("/home/pifinder/.claude/jobs/f6a5d765/tmp")
OUT_DIR = MEASUREMENTS_DIR / "ssd1333"

RUNS = [
    ("sweep-contrast-1d.json", "contrast-1d-20260802b.jsonl"),
    ("sweep-master-1d.json", "master-1d-20260802.jsonl"),
    ("sweep-ceiling-1d.json", "ceiling-1d-20260802.jsonl"),
    ("sweep-precharge-1d.json", "precharge-1d-20260802.jsonl"),
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

        for spec_name, journal_name in RUNS:
            with open(SPEC_DIR / spec_name) as handle:
                spec = json.load(handle)
            rig.journal_path = OUT_DIR / journal_name
            if rig.journal_path != first_journal:
                rig.journal(rig_record)
            print(f"\n=== {spec['description']} -> {journal_name} ===")
            run_sweep(rig, spec, set())
    print("\nall sweeps complete")


if __name__ == "__main__":
    main()
