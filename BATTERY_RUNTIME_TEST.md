# Battery runtime test — runbook

This branch (`battery-runtime-test`) is the bench harness for measuring rev4
real-world runtime and calibrating the state-of-charge curve. It is
**throwaway — never merge it**. The methodology and the definition of what the
resulting percentage *means* live on main in
[`docs/adr/0020-soc-as-runtime-fraction.md`](docs/adr/0020-soc-as-runtime-fraction.md);
this file is the operational how-to.

## What the branch changes

Every change is marked with a `BRANCH-ONLY` comment — `grep -rn "BRANCH-ONLY"
python/` lists all of them. In short:

- **Pinned typical load.** Exposure fixed at 400 ms / gain 20 with
  auto-exposure off (`camera_interface.py`), display sleep and screen-off
  forced off and brightness pinned to 255 (`main.py`). Every device runs the
  identical profile so runs are comparable.
- **Capture-and-substitute camera.** The camera loop starts in test mode:
  each cycle fires a *real* capture (so the sensor draws its normal power),
  discards it, and feeds the cached `test_images/pifinder_debug_02.png` to the
  solver — continuous realistic solve load with no sky. A constant "Lyr" in
  the title bar is the tell that it's working.
- **Telemetry to disk.** Both battery monitors (real BQ25895 and `-fb` fake)
  write one CSV row per 5 s poll to
  `~/PiFinder_data/battery_runtime/run_<pi-serial>_<stamp>/telemetry.csv`,
  flushed **and fsync'd** per row — the run ends in a hard power cut and the
  last row records the cutoff voltage that anchors 0%. `run_metadata.json`
  records the device and the pinned profile.

## Running a discharge test

1. Deploy the branch to the unit and restart PiFinder:
   `git fetch && git checkout battery-runtime-test`, then restart the service.
   The console shows `BATTERY RUNTIME TEST: logging` and `... camera pinned`
   at startup.
2. Leave it plugged in until STATUS shows **Charged** (charge done, not just
   "on external power").
3. **Pull the cable.** No manual timing needed — the `on_external_power`
   column flipping 1→0 is the discharge clock's t=0.
4. Walk away. Don't press keys, don't move it (the IMU stays quiet; the pinned
   load does the work). Leave WiFi in its normal state and note anything
   unusual for the run.
5. The unit will hard-power-off when the cell hits cutoff. Plug it back in,
   boot, and copy the newest `~/PiFinder_data/battery_runtime/run_*` directory
   off the device (each boot starts a fresh run dir, so the discharge run is
   the one *before* the current boot's).

Repeat per device / as many runs as wanted; the fit pools everything.

## Analyzing

```bash
cd python
python tools/battery_runtime_analysis.py --scan /path/to/collected/runs [--plot]
```

Per run it reports runtime, unplug/cutoff voltages, and a solver-liveness
verdict — a run where `solve_attempt_age_s` ever exceeded ~2 min had its load
die mid-discharge and is excluded from the fit automatically. Across clean
runs it prints a paste-ready `SOC_LUT` snippet for
`python/PiFinder/battery_bq25895.py`.

## Landing the results

The new `SOC_LUT` knots and `tools/battery_runtime_analysis.py` go to main
**together** in one PR (the imu2cam-tool precedent: derivation tools merge
with the values they derived). Raw telemetry CSVs stay out of the repo — keep
them somewhere durable and note the location in the PR.

## Dev-testing the harness without hardware

```bash
cd python
python -m PiFinder.main -fh -fb --camera debug --keyboard local -x
```

`-fb` runs the fake battery monitor through the same telemetry path, so rows
land in `~/PiFinder_data/battery_runtime/` on a dev machine (delete these —
the fake linear discharge must not be pooled into a real fit).

## Re-creating this in the future

If this branch has rotted beyond rebasing: re-apply the `BRANCH-ONLY` spots
listed above onto the then-current main (they are small and localized), keep
the telemetry schema in `battery_telemetry.py` compatible with the analysis
tool, and re-read ADR 0020 — the pinned profile must match whatever "typical
load" means for the hardware being measured, and changing it invalidates
pooling with old runs.
