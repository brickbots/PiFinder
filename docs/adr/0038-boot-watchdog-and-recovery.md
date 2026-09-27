# A self-arming boot watchdog rolls back failed trials; recovery mode is the update screen alone (proposed)

**Watchdog (in use, `pifinder-watchdog.service`).** A generation is a **trial** until it passes one boot health check. The health check passes when the app itself declares that its UI is live (systemd READY from the first drawn frame) and then stays up for a short time. A passed trial **confirms** the generation, and a ledger on the Pi records it (`/var/lib/pifinder/confirmed-generations`). Each boot of a generation that is not confirmed is a trial, whichever build installed it. So the protection does not depend on the code of the previous system. A trial that fails rolls back to the newest confirmed generation, captures the journal to `PiFinder_data`, and tells the user on the screen.

The watchdog never rolls back a confirmed generation. A cold night or a slow SD read must not downgrade a Pi that worked. If a confirmed generation's app fails, the watchdog only shows an advisory that names the recovery hold.

**Recovery mode (proposed, not built).** Holding the square-equivalent input at power-on starts a stripped app with only the update screen: display and keypad, no camera, solver or positioning. It shows the local generations, marks the confirmed ones, and offers the internet channels. A generation pick is sticky: it becomes the boot default. An internet pick installs through the normal upgrade and faces a normal trial. If recovery mode itself fails its health check, the Pi falls back to a blind rollback to the newest confirmed generation. Today only the advisory text exists (`nixos/services.nix`), and no code detects the hold.

## Considered options

- **Trial only when the upgrade writes a marker, rejected.** The first design. A Pi upgraded by an older build that did not write the marker got one unprotected boot. On 2026-07-03 the first v3.0.0-beta looped this way with no rollback.
- **Roll back on any repeated boot failure, rejected.** A transient failure would downgrade a confirmed build without a reason.
- **A separate minimal recovery tool, rejected.** A second UI with its own generation list and install code, which would age apart from the real one.
- **Blind rollback only, rejected.** The user often wants a specific version or a fresh install from a channel.

## Consequences

- The marker that the upgrade writes (`/var/lib/pifinder/trial-generation.json`) is only a hint. It names the exact system before the upgrade, camera specialisation included. The ledger is what counts. Loss of the ledger is harmless: a healthy generation confirms again.
- A failing trial with no generation to roll back to (a first install) shows a failure message and stays up for rescue, and it does not loop.
- **Known gap:** the watchdog runs only after the root file system is mounted. A build that stops in U-Boot, the kernel or the initrd boots the same entry again on each power cycle, with a black screen. On 2026-09-26 a CM4 stopped in the initrd this way, and recovery needed a change of `extlinux.conf` on the card. The chosen fix, not built yet, is U-Boot `bootcount` with `altbootcmd`: the confirm step resets the counter, and above the limit U-Boot boots the previous entry. It is preferred over Raspberry Pi `tryboot`, which works on partitions and would force an A/B layout.
- The upgrade and the first boot refuse a build that cannot mount the root of the Pi ([ADR 0039](./0039-card-layout-and-migration.md)). That closes the cause of the 2026-09-26 failure, but not the gap.

Replaces NixOS ADR 0005 (watchdog) and 0006 (recovery mode).
