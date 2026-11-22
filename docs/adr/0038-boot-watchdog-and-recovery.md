# A self-arming boot watchdog rolls back failed trials; recovery mode is the update screen alone

**Watchdog (in use, `pifinder-watchdog.service`).** A generation is a **trial** until it passes one boot health check. The health check passes when the app itself declares that its UI is live (systemd READY from the first drawn frame) and then stays up for a short time. A passed trial **confirms** the generation, and a ledger on the Pi records it (`/var/lib/pifinder/confirmed-generations`). Each boot of a generation that is not confirmed is a trial, whichever build installed it. So the protection does not depend on the code of the previous system. A trial that fails rolls back to the newest confirmed generation, captures the journal to `PiFinder_data`, and tells the user on the screen.

The watchdog never rolls back a confirmed generation. A cold night or a slow SD read must not downgrade a Pi that worked. If a confirmed generation's app fails, the watchdog only shows an advisory that names the recovery hold.

**Recovery mode (in use, `pifinder-recovery-hold.service`).** Holding SQUARE at power-on starts a stripped app with only the update screen: display and keypad, no camera, solver or positioning.

- `pifinder-recovery-hold` runs once per boot, early in `sysinit.target`, before `pifinder.service`. It scans the keypad matrix ten times in 0.5 s with the pins and the scheme of `keyboard_pi` (`PiFinder/recovery_hold.py`). The scheme is the same on rev3 and rev4. Rev4 has a second SQUARE at matrix position (4,4).
- The hold counts only when a SQUARE switch is closed and no other switch is closed, in every scan. A chord or a matrix fault is not a hold.
- On a hold it writes `/run/pifinder-recovery-mode` and shows "RECOVERY MODE" on the screen. Only root can write the flag, and each boot clears it.
- A failure of the detection never stops a normal boot. `pifinder.service` only wants the unit, the script always exits 0, and a time limit of 30 s stops a scan that hangs.
- With the flag, `pifinder.service` starts `PiFinder.recovery` in place of `PiFinder.main`. The recovery app runs the display and `UISoftware` in one process and the keypad scanner in a second process. On rev4 a thread reads the battery charger, so Install needs USB-C power as in the normal app. It starts no camera, solver, IMU, GPS, integrator, web server or sound process. `cedar-detect` and `pifinder-uboot-update` do not start in recovery mode.
- `UISoftware` shows the local generations first (the Rollback channel), with a check mark on the confirmed ones, then the internet channels. Without a WiFi client connection it shows the Rollback channel alone, because a rollback needs no internet.
- A pick, a generation or an internet build, installs through the normal upgrade (`PiFinder.nixos_upgrade`). The upgrade sets the system profile to the pick, so the pick becomes the boot default. A pick that is not confirmed faces a normal trial.
- In recovery mode the running system can be the one whose app fails. So the trial marker and the U-Boot boot counter name the newest confirmed generation as the fallback, not the running system. The upgrade then also deletes no old generations, so that confirmed generation stays.
- The recovery app sends READY=1 after its first frame. The watchdog checks its health like the health of the normal app, but a recovery boot never confirms a trial and never rolls one back. When the recovery app fails its health check, the watchdog does a blind rollback to the newest confirmed generation that is not the running one. With none, it shows a failure message and stays up for rescue.

## Considered options

- **Trial only when the upgrade writes a marker, rejected.** The first design. A Pi upgraded by an older build that did not write the marker got one unprotected boot. On 2026-07-03 the first v3.0.0-beta looped this way with no rollback.
- **Roll back on any repeated boot failure, rejected.** A transient failure would downgrade a confirmed build without a reason.
- **A separate minimal recovery tool, rejected.** A second UI with its own generation list and install code, which would age apart from the real one.
- **Blind rollback only, rejected.** The user often wants a specific version or a fresh install from a channel.

## Consequences

- The recovery hold needs SQUARE held from power-on until "RECOVERY MODE" shows, about 10 to 20 s. The scan runs only when `sysinit.target` starts, not in the boot loader or the initrd.
- The rollback notice (`upgrade_failed.json`) has a `by` field: `trial`, `recovery` or `boot counter`. After a failed recovery the app shows "Recovery failed".
- The marker that the upgrade writes (`/var/lib/pifinder/trial-generation.json`) is only a hint. It names the exact system before the upgrade, camera specialisation included. The ledger is what counts. Loss of the ledger is harmless: a healthy generation confirms again.
- A failing trial with no generation to roll back to (a first install) shows a failure message and stays up for rescue, and it does not loop.
- The watchdog runs only after the root file system is mounted. A build that stops in the kernel or the initrd never reaches it. On 2026-09-26 a CM4 stopped in the initrd this way, and recovery needed a change of `extlinux.conf` on the card. **The U-Boot boot counter** closes this gap (`nixos/pkgs/uboot-sd.nix`, `pifinder-bootcount` in `nixos/services.nix`):
  - U-Boot keeps a 4-byte file, `pifinder.bootcount`, on the FAT partition: magic, version, count and `upgrade_available` (U-Boot `BOOTCOUNT_FS`). With `upgrade_available=0`, U-Boot neither counts nor writes.
  - Before the reboot into a trial, the upgrade sets `upgrade_available=1` and writes `pifinder-fallback.env` with the extlinux entry of the system that runs now (`pxe_label_override=nixos-<gen>-<camera>`).
  - Each boot of the trial counts. Above `bootlimit` (3), U-Boot runs `altbootcmd`: it imports `pifinder-fallback.env` and boots that entry.
  - The kernel parameters `boot.panic_on_fail panic=10` restart the Pi after a failure in the initrd or a kernel panic, so the count goes up without a hand on the power switch. A hang with no panic still needs power cycles.
  - The watchdog stops the counter on each healthy boot. When it finds the counter on while a confirmed generation runs that is not the profile's generation, U-Boot has fallen back: the watchdog makes the running generation the default again and writes `upgrade_failed.json`.
  - `pifinder-uboot-update` puts the U-Boot of the build on the FAT partition when it differs, only from a confirmed generation, and keeps the replaced one as `u-boot-rpi4.bin.old`.
  - Chosen over Raspberry Pi `tryboot`, which works on partitions and would force an A/B layout, and over a counter in the U-Boot environment (`BOOTCOUNT_ENV`): a saved environment replaces the built-in one, `bootcmd` included, and an older U-Boot would read a partial file.
  - Risk: a new U-Boot that does not start stops the device before any rollback. The `.old` copy then goes back with a card reader.
- The upgrade and the first boot refuse a build that cannot mount the root of the Pi ([ADR 0039](./0039-card-layout-and-migration.md)). That closes the cause of the 2026-09-26 failure.

Replaces NixOS ADR 0005 (watchdog) and 0006 (recovery mode).
