# extlinux and kernels live on the ext4 root; the FAT partition is firmware-only

A custom U-Boot (`CONFIG_CMD_SYSBOOT`) reads `extlinux.conf` and the per-generation kernels from `/boot` **on the ext4 root** (`mmc 0:2`); the FAT partition carries only what the GPU firmware itself must parse — `config.txt`, `start*.elf`, U-Boot, DTBs — written once at install and never touched at runtime. NixOS mutates `/boot` on every generation switch (upgrade, rollback, camera specialisation, watchdog auto-rollback, `set-extlinux-default`), and those rewrites must be crash-safe: ext4 renames are atomic, FAT's are not — a power cut mid-rewrite on FAT can corrupt the one file the boot chain needs, which is unacceptable for a bootloader the watchdog rewrites unattended.

## Considered options

- **Everything on FAT (Raspbian convention: firmware loads the kernel directly), rejected.** No atomic rename (crash-unsafe generation switches), no symlinks, and per-generation kernels+initrds (~50MB each, `configurationLimit` of them plus specialisation entries) outgrow a 256MB firmware partition.
- **extlinux on FAT, kernels on ext4, rejected.** Splits one logical unit (the boot menu and what it points at) across filesystems and still leaves the menu rewrite non-atomic.

## Consequences

- The partition most fragile to corruption (FAT, which the GPU bootloader must parse) is also the one never written after install.
- The tarball layout follows: its top-level `boot/` is the firmware payload, while `rootfs/boot` is a **populated** directory — anything consuming the tarball must not assume Raspbian's everything-in-FAT layout. The migration initramfs did exactly that (empty-`/boot` assumption + extlinux-on-FAT verifications) and failed the first real migration against this layout (2026-07-05); it now stages the firmware payload aside and verifies each partition for what its boot-chain stage actually needs.
