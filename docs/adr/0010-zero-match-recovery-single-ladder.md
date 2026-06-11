---
status: accepted
---

# Zero-match recovery: one fixed-ladder strategy (keep Sweep, retire the rest)

Zero-match recovery — auto-exposure's escape hatch when a solve attempt matches nothing — accumulated four selectable strategies behind the Experimental → "AE Algo" menu: Sweep, Exponential, Reset, and Histogram. We narrowed recovery's responsibility to exactly one failure cause — **the exposure being badly wrong** (dusk/dawn, slew into bright sky, returning from daytime alignment with a daylight exposure) — and on that scope the field collapses: we keep the Sweep ladder as the only recovery behavior and retire the other three strategies, the `ZeroStarHandler` plugin seam, the `set_ae_handler` command, the "AE Algo" menu entry, and the `auto_exposure_zero_star_handler` config key (stale config values are ignored and fall back to the one behavior).

Why Sweep wins: its ladder ordering `[400, 800, 1000, 200, 100, 50, 25] ms` encodes the night-time prior — start at the known-safe shipped default, climb first because too-dark is the dominant failure at night, then try short. Reset is a degenerate Sweep: its 400 ms target is Sweep's first rung, but it stops searching there and strands the camera if 400 ms is also wrong. Exponential differs only in rung spacing, and its strictly ascending order starts at the least-likely exposures for the scoped failure. Histogram existed for the defocused case ("no stars detected, likely defocused"), which is no longer recovery's job — the focus indicator (ADR 0005-focus-hfd-self-contained-in-ui) gives users a plate-solve-independent focus aid.

Explicitly out of recovery's scope, by decision rather than omission: defocus, transient blockage (clouds, capped scope, pointed at the ground), and solver-side failures where centroids are plentiful but tetra3 matches none. No exposure change fixes those, and recovery should not thrash trying.

## Consequences

- The recovery logic becomes a single concrete class — it carries real state (ladder position, per-rung repeat count) — not an ABC with one implementation. Re-introducing a strategy seam later is cheap if field evidence demands it; carrying dead abstraction is not.
- Whether the shipped default exposure regime stays manual 0.4 s or becomes solver-driven auto-exposure is a separate open question (flagged in `docs/ax/camera.md`), deliberately not decided here.
