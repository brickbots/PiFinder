# NixOS releases and the Pi OS migration

How a NixOS release is made and published, how a Pi OS PiFinder moves to
NixOS, and the faults that we know. Read this before you start a release or
change the migration.

Decisions: [ADR 0037](../docs/adr/0037-nixos-builds-cache-and-update-channels.md)
(cache and channels), [ADR 0039](../docs/adr/0039-card-layout-and-migration.md)
(card layout and migration). Terms: [NixOS CONTEXT](../docs/ax/nixos/CONTEXT.md).

> The repo-root `RELEASE.md` holds the release notes of one version. This
> file is about the release process.

## Where things are

| Item | Place | Note |
| --- | --- | --- |
| NixOS source | `mrosseel/PiFinder`, branch `nixos` | Releases are built from here. |
| Release workflow | `brickbots/PiFinder`, branch `ci/btrfs-migration-release` | Its `release.yml` and `.github/scripts/` are copies of the files on `nixos`. |
| Update manifest | `brickbots/PiFinder`, branch `nixos-manifest`, `update-manifest.json` | Devices read only this file. A build that is only in the `mrosseel` manifest does not show on a device. |
| Migration gate | `brickbots/PiFinder`, branch `release`, `migration_gate.json` | Flag `nixos_migration`. |
| Release assets | GitHub releases on `brickbots/PiFinder` | SD images, migration tarball, `.sha256` files. |
| Dev cache | `cache.pifinder.io/pifinder` | Beta, PR and trunk builds. Retention 90 days. |
| Release cache | `cache.pifinder.io/pifinder-release` | Stable builds. Kept for ever. |
| Delta server | `deltas.pifinder.io` | Patches between store paths for upgrades. |

Devices also use `cache.nixos.org` for paths that nixpkgs builds.

## What a release makes

| Artifact | Where | Who reads it |
| --- | --- | --- |
| System closure | Attic: `pifinder-release` (stable) or `pifinder` (beta) | Every NixOS device that installs the release. |
| Manifest entry | `nixos-manifest`, first in the `stable` or `beta` list | The Software screen, and 2.6.4 for the migration target. |
| `pifinder-vX.Y.Z[-beta].img.zst` | Release asset | People who flash a new card (lean image). |
| `pifinder-full-vX.Y.Z[-beta].img.zst` | Release asset | Only when `flake.nix` has catalog images. |
| `pifinder-migration-vX.Y.Z[-beta].tar.zst` | Release asset | Pi OS 2.6.4, once. Only when `new_migration_tarball` is on. |
| Git tag | Source repo | Only when the source repo is the repo that runs the workflow. A release from `mrosseel/PiFinder` makes no tag. |

## Release rules

1. Release only a commit that is merged into `nixos` and has green CI.
2. A **beta** goes to the dev cache, and Attic deletes its closure after the
   90-day retention. A **stable** release goes to
   `pifinder-release`, which keeps it for ever.
3. Open the migration gate only when a **stable** release is in the
   manifest. The migration downloads the newest system at first boot. A beta
   closure can be gone by then.
4. Before each release, compare the release files on the brickbots CI
   branch with `nixos`:

   ```sh
   git fetch https://github.com/brickbots/PiFinder.git ci/btrfs-migration-release && ci=$(git rev-parse FETCH_HEAD)
   git fetch https://github.com/mrosseel/PiFinder.git nixos && nixos=$(git rev-parse FETCH_HEAD)
   git diff --stat "$ci" "$nixos" -- .github/workflows/release.yml \
     .github/scripts/update_manifest.py .github/scripts/publish_manifest.sh
   ```

   No output means that the files are the same. If they are different, add a commit to the CI branch that copies them.
   Push it as a fast-forward. Never force-push.
5. Set `new_migration_tarball` only when the migration must change. See
   [When a new tarball is needed](#when-a-new-tarball-is-needed). When it is
   off, the new entry names the tarball of the newest release that has one.
6. Do not delete a release while a manifest entry names its tarball. Many
   entries can name the same tarball.
7. The `release` branch of brickbots holds Pi OS code. Its `version.txt` stays
   a 2.6.x version, because Pi OS units `git pull` that branch.

## Start a release

```sh
gh workflow run release.yml -R brickbots/PiFinder --ref ci/btrfs-migration-release \
  -f version=3.1.3 -f type=stable \
  -f source_repository=mrosseel/PiFinder -f source_branch=nixos \
  -f new_migration_tarball=false \
  -f notes="..."
```

- `version`: semver, no `v`. A beta gets the tag `vX.Y.Z-beta`.
- The run takes about 15 minutes when Attic already has most paths.

Then check:

1. The run ends with `success`.
2. The release has the expected assets and `.sha256` files.
3. In the live manifest, the entry is first in its list, `available` is
   `true`, and it has `migration_v2_url` and `migration_v2_sha256_url`:

   ```sh
   curl -s https://raw.githubusercontent.com/brickbots/PiFinder/nixos-manifest/update-manifest.json \
     | jq '.channels.stable[0], .channels.beta[0]'
   ```

4. The `.sha256` URL of the tarball returns 200. For some minutes after a
   publish, GitHub can return 504 for a new asset.

## The migration from Pi OS

### Steps

1. **Offer.** 2.6.4 reads `migration_gate.json`. When `nixos_migration` is
   `true`, the Software screen offers the migration. Seven presses of square
   offer it also when the gate is closed. When the gate is closed and no one
   presses square seven times, 2.6.4 shows no version 3 release.
2. **Target.** 2.6.4 goes through the manifest lists in this order:
   stable, beta, unstable. In each list it goes from the top. It takes the
   first entry with `available: true` and both `migration_v2` keys. The
   order of the list decides, not the version number. Unstable entries have
   no migration keys.
3. **Checks.** Pi 4 or CM4, 1800 MB RAM, a 16 GB card, 4 GB free, WiFi in
   client mode, a supported display, the standard card layout
   (`python/scripts/nixos_migration_calc.py`).
4. **Prepare (Pi OS).** Download the tarball, check its sha256, make a
   migration initramfs on the boot partition, reboot.
5. **Convert (initramfs).** `btrfs-convert` changes partition 2 to btrfs in
   place. The initramfs makes the `PiFinder_data` subvolume, deletes the Pi OS
   files, extracts the tarball, writes the FAT partition, and keeps WiFi,
   password, SSH keys, access point name and camera type. Then it reboots.
6. **First boot (minimal system).** It reads the manifest and takes the
   first available `store_path` in stable, then beta, then the `nixos` trunk.
   This is the newest system, not the release of the tarball. It downloads
   that system, activates the camera from Pi OS, switches, deletes the
   minimal system and reboots.
7. **Full system.** It deletes `ext2_saved` and runs one btrfs balance.

All network steps come before the conversion. A failed download leaves Pi OS
as it was.

### The fixed contract with 2.6.4

When 2.6.4 is released, these items cannot change for 2.6.4 units:

- the gate URL and the flag `nixos_migration`;
- the manifest URL, the keys `migration_v2_url` and `migration_v2_sha256_url`,
  and the channel order;
- the tarball format: `tar.zst` with a top-level `boot/` (FAT files) and
  `rootfs/` (the btrfs root, with `nix-path-registration` and
  `boot/extlinux/extlinux.conf`).

For a change to this contract, release a new Pi OS version that reads a new
key, for example `migration_v3_url`.

Pi OS 2.6.3 and older read `migration_url` and `nixos_for_everyone`. Never
write `migration_url` to the manifest, and keep `nixos_for_everyone` false.
2.6.3 would start its old ext4 migration with a btrfs tarball.

### When a new tarball is needed

The tarball holds a minimal system that installs the newest release at first
boot. So one tarball serves many releases. Build a new one only when the
migration itself must change:

- a fault in the FAT files: `config.txt`, U-Boot, firmware, device trees;
- a fault in the first-boot step: manifest, download, switch, camera;
- new hardware that the kernel of the tarball cannot use, for example a new
  WiFi chip;
- a change of the card layout, for example the root is not btrfs on
  partition 2.

A change to the app or to the full system does not need a new tarball.
Build a new tarball with a stable release. The tarball has a built-in target
(the system of its own release), which it uses only when it cannot read the
manifest. A stable target stays in `pifinder-release`.

A new tarball needs the migration simulation and a hardware check on a Pi 4
and a rev 4 (CM4) before the manifest names it.

## Known faults

- **The release workflow on brickbots `main` is old.** It writes
  `migration_url`, and 2.6.3 units then start the ext4 migration. Start
  releases only from the CI branch until `main` has the `nixos` workflow.
- **The FAT partition does not change after the migration.** NixOS updates
  only U-Boot there (`pifinder-uboot-update`). A fix in `config.txt` or a
  device tree on FAT reaches new migrations and new cards, not cards that
  are already migrated.
- **Rev 4 (CM4): GPIO14 is the power-off line** (ADR 0034). A byte on the UART
  TX pin cuts the power. Do not turn on a serial console on the CM4.
  `config.txt` sets `gpio=14=ip,pu` in `[cm4]`, and the CM4 device tree has
  `uart1` disabled.
- **The simulation is a Pi 4B.** QEMU does not test the CM4. A change to the
  boot path needs a rev 4 hardware check.
- **Beta closures expire.** After the 90-day retention, a device cannot
  install the beta. A gate with only betas in the manifest fails at first boot
  after that time.
- **The manifest marks an entry available only when the cache serves its
  narinfo.** A failed Attic push gives `available: false`, and 2.6.4 skips
  that entry.
- **Read the live manifest.** A local copy of the `nixos-manifest` branch can
  be older than the last release. Use the raw URL in
  [Start a release](#start-a-release).
- **The initrd module list is forced.** `flake.nix` sets
  `boot.initrd.availableKernelModules` with `lib.mkForce`. This also removes
  the modules that NixOS modules add, for example the btrfs checksum modules.
  When a kernel update changes a built-in driver to a module, stage 1 does not
  have it. Kernel 6.18 did this to `crc32c`, and the root did not mount. Add
  each module that stage 1 needs to that list.

## Kernel and package updates

The kernel is the Raspberry Pi vendor kernel. Its tag and hash are fixed in
`nixos/pkgs/pifinder-kernel.nix`, so it changes only when that file changes.
An update of `nixos-hardware` does not change it. An update of nixpkgs
rebuilds it with the new compiler, at the same version.

To update the kernel:

1. Find the newest `stable_YYYYMMDD` tag of `raspberrypi/linux`.
2. Set `tag` and `modDirVersion` in `pifinder-kernel.nix`. `modDirVersion` is
   `VERSION.PATCHLEVEL.SUBLEVEL` from the `Makefile` of that tag.
3. Get the hash:
   `nix store prefetch-file --unpack https://github.com/raspberrypi/linux/archive/refs/tags/<tag>.tar.gz`.
4. Check that `nixos/patches/imx290-optical-black-stream.patch` applies, and
   that the camera overlays are in the new source.
5. Open a PR with the `testable` label. CI compiles the kernel and pushes it to
   Attic.
6. Run the migration simulation. It also boots the full system with the new
   initrd.
7. Test the camera, GPS, display and keypad on a Pi 4 and a rev 4.

To update nixpkgs: `nix flake update nixpkgs`, then steps 5 to 7.
`nixos-hardware` follows our nixpkgs, so the lock has only one nixpkgs.

## Tests

| Test | Command | Time |
| --- | --- | --- |
| Migration simulation | `nixos/tests/migration-e2e/run.sh <PiFinder_2.6.3.img> <Pi OS checkout>` | about 2 hours, needs sudo and 40 GB |
| Upgrade simulation | `nixos/tests/delta-e2e/run.sh` | see the script header |
| Hardware | migrate a Pi 4 and a rev 4 from a 2.6.4 card | before the gate opens |

## Files

| File | Role |
| --- | --- |
| `.github/workflows/release.yml` | Release workflow (copy it to the brickbots CI branch) |
| `.github/workflows/nixos-pr-build.yml` | Testable PR and trunk builds, unstable entries |
| `.github/scripts/update_manifest.py` | Writes manifest entries |
| `.github/scripts/publish_manifest.sh` | Pushes the manifest branch, with retries |
| `flake.nix` (`migrationTarball`) | Builds the migration tarball |
| `nixos/device.nix` (`pifinder-first-boot`) | First boot of the minimal system |
| `nixos/migration.nix` | Migration services in both systems |
| `python/PiFinder/ui/software.py` | Software screen and manifest reader |
| Pi OS line: `python/scripts/nixos_migration*.sh`, `nixos_migration_calc.py` | The 2.6.4 side of the migration |
