# Handoff: SSD1333 dimming-policy refit (stage 3 of 3)

You are the stage-3 agent. Stage 1 built the photometer rig
(`PiFinder.panel_photometry`); stage 2 (done, 2026-08-02) measured the
panel's response surface. **Your job: refit `DisplaySSD1333.set_brightness`
— the level → axis-state policy — against the measured surface, and verify
the shipped curve end-to-end on the rig.** This file lives in the repo
because a previous handoff died with `/tmp` on a reboot.

## Read these first (in order)

1. `docs/ax/display/CONTEXT.md` — vocabulary (note the new terms: drive
   product, pre-charge glow).
2. `docs/ax/display/ssd1333-response.md` — the measured model. Everything
   below is a summary of it; it and the journals in
   `docs/ax/display/measurements/ssd1333/` are your ground truth.
3. `docs/adr/0023-ssd1333-brightness-three-axis.md` — the shipped policy
   and its (now partly falsified) constants. Amend it as part of your work;
   `ssd1333-response.md` §7 lists exactly which claims fell.

## The measured facts your fit must respect

- Contrast and master are ONE axis: flux depends only on the drive product
  P = contrast × (master+1). Dark below P=4; cliff to 28.5 % of reference
  at P=4; nearly flat to P≈32; ≈ √P above P≈128. Full P range gives only
  6.9× of light.
- The ceiling duty law `(n−1)/30` is real (±1 % at reference drive) — the
  only wide, near-linear axis.
- Separability FAILS: pre-charge spans 32× at low drive, 1.29× at
  reference. Use the measured families/dim slice, not multiplication.
- Dim regime (ceiling 4, master 0): pre-charge is the dial (21× over codes
  6→23), contrast trims ≤10 %. Pre-charge cut-out there ends at code 3;
  codes 4–7 are usable and reach the tonal-rule floor of 148 ADU/s.
- Reachable span within the tonal rule: ≈3.8 decades (148 → ~1.0e6 ADU/s
  at the ≈75 %-of-clean-max top). The shipped policy's bottom sits 40×
  above the floor.
- Pixel-value remap math is validated at reference drive but bends with
  drive; the value-64 canary stays distinct at all measured operating
  points (ratios 0.10–0.37).

## User decisions that still stand (don't re-litigate)

- Keep the dim-weighted knee shape; constants re-derived from the data;
  measured emission floor sets the bottom; top ≈75 % of max clean output
  (soft).
- Tonal-range rule: value-64 must stay photometrically distinct from
  value-255 at every lit setting → ceiling ≥ 4 (`MIN_TONAL_CEILING`).
- Eyeball constants the rig cannot see stand: `MAX_CONTRAST = 160`,
  blooming cap (`MAX_BRIGHTNESS` 70 %) — unless the user re-checks
  visually.
- Harness stays panel-agnostic; SSD1351 is a later rig swap.

## Suggested shape (from ssd1333-response.md §8 — yours to refine)

Bright regime: ride P at ceiling 31 (√P → smooth steps). Mid: lower the
ceiling on the duty law at the drive floor. Dim: hold ceiling 4 / P 4,
walk pre-charge 23 → 4; bottom steps are coarse (pc 4→6 ≈ 2.5–6×/code) —
that is the panel's floor, echo the ADR's existing "panel's floor, not the
curve's" stance. Tests in `tests/test_ssd1333_brightness.py` hold the
canary line; extend them to the new constants.

## Verification (non-negotiable)

Sweep your final level curve end-to-end on the rig (one spec: one point
per level, axes as your policy computes them) and check monotonicity,
step sizes against the knee-shape intent, and the 148 ADU/s bottom.
Run `python3 -m PiFinder.panel_photometry selftest --panel ssd1333`
first — all gates must PASS; `pifinder`/`pifinder_splash` stopped; system
python3, no venv; unit off charger unless the enclosure was re-verified
with `monitor` while charging. Always go through the harness's capture
paths. Old mid-range configs will shift again — call that out in the PR
like the 2026-07 reshape did.

## Repo state you inherit

PR #568 carries everything: stage-1's harness (`panel_photometry.py`,
driver changes in `displays.py`/`ssd1333_device.py`, `precharge_sweep.py`,
ADR 0023 revision, `test_ssd1333_brightness.py`) and stage-2's journals,
`ssd1333-response.md`, CONTEXT.md vocabulary, and this file. Confirm it
merged before relying on file paths here.
