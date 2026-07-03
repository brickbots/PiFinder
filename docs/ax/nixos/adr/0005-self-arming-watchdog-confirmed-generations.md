# Boot watchdog is self-arming via a confirmed-generations ledger; confirmed generations are never auto-rolled-back

A generation is a **trial** until it passes one boot health check, which **confirms** it permanently on that device (recorded in a device-local ledger). Any boot of an *unconfirmed* generation is a trial — regardless of which build installed it — so recovery never depends on the previous system's code: the version-skew hole where an older build (unaware of trial markers) installs a broken new one and leaves it unprotected, which is exactly how the first v3.0.0-beta crash-looped with no rollback on 2026-07-03. Confirmed generations are never auto-rolled-back: a transient failure in the field must not cause a surprise downgrade.

## Considered options

- **Marker-armed only (upgrade writes a trial marker; no marker → nothing to watch), rejected.** The original design. Protection depends on the *installing* build knowing to arm the marker — any device upgrading from an older build gets one unprotected hop, proven in the field.
- **Auto-rollback on any repeated boot failure (no confirmation concept), rejected.** Self-heals late-life breakage, but a confirmed build failing transiently (cold night, flaky SD read) would be silently downgraded — the failure mode the trial/confirm split exists to prevent.

## Consequences

- Persistent breakage of an already-confirmed generation does **not** self-heal — deliberate. It is covered by the explicit recovery ladder instead: the Software screen's Rollback channel, a planned power-on keypad recovery chord (rollback without any working UI), and SSH.
- The upgrade-written trial marker survives as a *hint* (it names the exact pre-upgrade system, camera specialisation included); the ledger is what's load-bearing. Rollback targets are chosen newest-first from the profile, preferring confirmed generations.
- Ledger loss is benign: a healthy generation simply re-confirms on its next boot; an unhealthy one gets a rollback it genuinely needs.
- A failing trial with no rollback target at all (first-ever install) shows an on-screen failure message and stays up for rescue instead of boot-looping.
