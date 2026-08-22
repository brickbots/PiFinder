# NixOS ADRs

Architecture-decision records for the **NixOS** context (NixOS build, binary cache, update channels, on-device upgrade/rollback). Numbered locally — `0001`, `0002`, … — independent of the repo-root `docs/adr/`.

**Why a separate namespace.** These decisions are fork-only (`mrosseel/PiFinder`, the NixOS line) and have no counterpart upstream (`brickbots/PiFinder`). The root `docs/adr/` is shared with upstream and is merged on every sync; putting a fork ADR there means picking a number that will collide with the next upstream ADR, and a rename on the fork is undone/duplicated by the next merge. A context-local namespace keeps fork deploy decisions collision-proof until the NixOS line becomes upstream mainline, at which point these fold into the shared sequence.

- [0001 — Self-hosted Attic for NixOS binary distribution](./0001-attic-binary-cache.md)
- [0002 — Update channels stay Release-based (stable/beta) over a live main+PR unstable; rollback via reinstall + passive yank](./0002-update-channels-and-rollback.md)
- [0003 — Migration tarball resolves its full system from the update manifest at first boot (rides latest stable), instead of pinning a closure](./0003-migration-tarball-rides-latest-stable.md)
- [0004 — Migration tarball is published as a (pre)release asset, not a built-once file (amends 0003)](./0004-migration-tarball-published-per-release.md)
- [0005 — Boot watchdog is self-arming via a confirmed-generations ledger; confirmed generations are never auto-rolled-back](./0005-self-arming-watchdog-confirmed-generations.md)
- [0006 — Recovery mode is the update screen in isolation, with a blind-rollback fallback — not a separate minimal tool](./0006-recovery-mode-reuses-update-screen.md)
- [0007 — extlinux and kernels live on the ext4 root; the FAT partition is firmware-only](./0007-boot-on-ext4-fat-firmware-only.md)
- [0008 — The imx462 camera gets an explicit 74.25 MHz xclk overlay because fdtoverlay drops overlay parameters (proposed)](./0008-imx462-xclk-override.md)
