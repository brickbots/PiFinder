.. _nixos:

NixOS: Migration, Images & Releases
===================================

Starting with v3.0.0, the PiFinder ships as an **immutable NixOS image** rather
than a Raspberry Pi OS install with the app cloned on top. This page is the
developer/maintainer map to that change. It does not repeat the deep reference
material — it points at it — and it deliberately leaves the *end-user*
walkthroughs (flashing a card, driving the update screen) to the user guide.

There are three distinct things to keep separate, and they have separate names:

- **In-place migration** — the one-time, on-device conversion of an existing
  Raspberry Pi OS PiFinder to NixOS.
- **Image build** — producing the writeable ``.img`` that flashes a *fresh* SD
  card.
- **System update** — swapping the running NixOS system for a newer prebuilt one
  pulled from the project's binary cache.

A fourth term clears up an old overload: the per-version Raspberry Pi OS data
fixups (``migration_source/v*.sh``) are **post-update actions**, not migrations.
"Migration" now means only the OS-level conversion above.

Where the detail lives
----------------------

This page is an index. The authoritative documentation is the in-repo reference
layer (see :ref:`dev_guide:Reference documentation and AI assistant skills`):

- ``docs/ax/migration/CONTEXT.md`` and ``docs/ax/migration.md`` — the **Migration**
  context: the in-place conversion, end to end. Lives on ``main`` (the migration
  code is already merged).
- ``docs/ax/nixos/CONTEXT.md`` and ``docs/ax/nixos.md`` — the **NixOS** context:
  build, publish, channels, on-device upgrade and rollback. Arrives with the
  NixOS system itself (PR #379).
- ``nixos/RELEASE.md`` — the release-engineering runbook: the build → image →
  tarball → cache → tag → manifest flow, plus "cutting a release" and hotfixes.
- ``docs/ax/nixos/adr/`` — decisions behind the cache and the channel/rollback
  model.

In-place migration (Raspberry Pi OS → NixOS)
--------------------------------------------

A deployed PiFinder converts itself by reflashing its own SD card. Because a
running OS cannot reformat the card it booted from, the work is done from a
throwaway initramfs that lives entirely in RAM; it saves the device's WiFi and
``PiFinder_data`` to RAM, formats both partitions, unpacks the new system, and
restores that state. The conversion is **destructive and one-way** — there is no
in-product path back to Raspberry Pi OS.

It is reached from the on-device **Software** screen two ways:

- **Migration gate** — the maintainer opens it fleet-wide by setting
  ``nixos_for_everyone`` in ``migration_gate.json`` on the ``release`` branch.
  Eligible devices are then offered it automatically.
- **Migration enable** — an individual user opts in early by pressing **SQUARE**
  seven times on the Software screen, regardless of the gate.

Either way the device first runs **pre-flight checks** (``nixos_migration_calc.py``):
a Pi 4, ≥ 1800 MB RAM, a ≥ 16 GB card in the stock two-partition layout, free
space, WiFi in **Client mode**, and a display the progress renderer supports.
The checks are all-or-nothing and run before anything is downloaded or touched.

The code is all under ``python/scripts/`` (``nixos_migration.sh``,
``nixos_migration_init.sh``, ``nixos_migration_calc.py``) with the UI in
``python/PiFinder/ui/software.py``. For the full sequence — staging the
initramfs, the reflash, data preservation, and the point of no return — read
``docs/ax/migration.md``.

To exercise the trigger path without a real device, the migration UIs are built
in the smoke harness (``tests/test_software.py``); the destructive initramfs
stage only runs on a real Pi 4.

Building an SD card image
-------------------------

A fresh card is flashed from ``pifinder-vX.Y.Z.img.zst``, a writeable disk image
published as a GitHub Release asset. It is built from the same release closure as
the running system — the release workflow runs ``nix build .#images.pifinder``
and the **migration tarball** (``pifinder-migration-vX.Y.Z.tar.zst``, consumed by
the in-place migration above) is extracted from that same image. The two release
assets are therefore always in lock-step: one flashes a blank card, the other
converts an existing one.

The image and the flake that produces it arrive with PR #379. The build steps
and asset list are documented in ``nixos/RELEASE.md`` (see *Artifacts* and
*Release flow*).

Updating a NixOS PiFinder
-------------------------

On NixOS, an update is not ``git pull`` — the device **downloads a prebuilt
system from the project's binary cache and switches to it**; it never compiles
anything. The on-device Software screen offers three **channels**:

- **stable** — official releases. The default for ordinary use.
- **beta** — pre-releases cut from the development branch, curated with notes.
- **unstable** — the live development tip plus individual open pull requests,
  each installable before merge. Hidden until unlocked (7× SQUARE on the update
  screen — a *different* gesture from migration enable, on a different screen).

Each channel entry names a version and a signed ``/nix/store`` path; the device
resolves it against the ``cache.pifinder.eu`` Attic cache and activates it. A bad
build is recovered by reinstalling an earlier stable/beta version (their closures
are retained in the cache forever), by an automatic single-generation rollback on
a failed boot, or by yanking a bad release. The mechanics — channels, the
manifest, the two caches and their retention, rollback and yank — are specified
in ``docs/ax/nixos/CONTEXT.md`` and
``docs/ax/nixos/adr/0002-update-channels-and-rollback.md``; the release-cutting
procedure is in ``nixos/RELEASE.md``.

This whole path — the channel UI, the cache, the manifest, and the on-device
updater — lands with PR #379.
