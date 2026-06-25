# Migration

The Migration context owns the one-time, on-device conversion of a deployed PiFinder from its Raspberry Pi OS install to NixOS. It runs on the old system, reflashes the SD card in place, and hands the device off to the **NixOS** context, which owns everything afterwards. It is a bridge, used once per device and never again.

> Companion architecture doc: [`../migration.md`](../migration.md).
> Downstream context: [`../nixos/CONTEXT.md`](../nixos/CONTEXT.md) (added by PR #379) owns image build and every update *after* migration.

## Language

### The event

**In-place migration**:
The one-time conversion of a running Raspberry Pi OS PiFinder into a NixOS PiFinder, performed on the device itself by reflashing its own SD card. Destructive and one-way: both partitions are reformatted, and there is no in-product path back to Raspberry Pi OS.
_Avoid_: "upgrade", "update" (those are the NixOS context's recurring **system update**, not this one-shot conversion); "install" (that is a fresh card from an **image build**).

**Post-update actions**:
The small, idempotent, per-version data and config fixups run after a Raspberry Pi OS *code* update (the `migration_source/v*.sh` scripts, stamped under `PiFinder_data/migrations/`). A legacy Raspberry Pi OS concept, unrelated to the conversion above and retired on NixOS.
_Avoid_: "migrations", "data migrations" — renamed precisely so "Migration" can mean only the OS-level event.

### Starting it

**Migration gate**:
The fleet-wide rollout switch (`migration_gate.json`, key `nixos_for_everyone`) fetched from the `release` branch. When open, eligible devices are offered the migration automatically; the maintainer controls the whole fleet by editing this one file.
_Avoid_: "killswitch" in prose (it is the rollout *control*, not only an off switch), "feature flag".

**Migration enable**:
The manual, per-device opt-in — a 7× SQUARE gesture on the Software screen — that turns the migration on for one device regardless of the **migration gate**. The path for early adopters before the gate opens.
_Avoid_: "unlock" (too generic, and the NixOS update screen has its own 7× SQUARE gesture that reveals the **unstable** channel — a different screen and a different effect), "secret menu".

**Pre-flight checks**:
The all-or-nothing eligibility test run before a migration may proceed (`nixos_migration_calc.py`): correct Pi model, enough RAM, an SD card of supported size and the stock two-partition layout, free space, WiFi in **Client mode**, and a display the **migration progress display** can drive. Any single failure blocks migration.
_Avoid_: "requirements check" (fine in user prose, but "pre-flight" is the canonical term), "validation".

### Doing it

**Migration tarball**:
The payload a migration consumes: a `.tar.zst` (`pifinder-migration-vX.Y.Z.tar.zst`) holding the new system's `boot/` and `rootfs/` trees. Self-contained — it is unpacked directly onto the SD card and does not depend on the binary cache. **Not** a flashable disk image.
_Avoid_: "image", "the img" (an **image build** produces `pifinder-vX.Y.Z.img.zst`, a different artifact for a different job — see Flagged ambiguities), "the closure".

**Migration initramfs**:
The minimal RAM-resident environment the device reboots into to perform the reflash. Because it lives entirely in RAM, it can reformat the very SD card the old OS booted from: it stages **preserved data** to RAM, formats both partitions, unpacks the **migration tarball**, restores the preserved data, then reboots into NixOS.
_Avoid_: "recovery image", "rescue mode", "the installer".

**Preserved data**:
The state carried across the wipe in RAM and written back onto the new system: the device's WiFi credentials (rewritten into NetworkManager keyfiles for NixOS) and its `PiFinder_data` (observations, configuration, observing lists, hostname). Everything else on the old card is discarded.
_Avoid_: "backup" (nothing is kept off-device; it is a transient in-RAM carry-over), "user data" alone (WiFi credentials are preserved too).

**Migration progress display**:
The standalone OLED renderer (`migration_progress`) that shows progress during the window when the normal PiFinder UI does not exist — after the old OS is gone and before NixOS boots. Why it must be its own self-contained binary, not the app.
_Avoid_: "splash", "the UI" (the app is not running at this point).

### Cross-context terms

- **Image build** / **SD image** — owned by [NixOS](../nixos/CONTEXT.md) (added by PR #379): produces `pifinder-vX.Y.Z.img.zst`, the flashable disk image for a *fresh* SD card. Migration consumes the sibling **migration tarball** instead; both are cut from the same release.
- **System update** / **channels** — owned by [NixOS](../nixos/CONTEXT.md): every update *after* a device is on NixOS. Migration is the one-time entry into that world and owns none of it.
- **Client mode** — the WiFi state (versus Access Point mode) required by **pre-flight checks**, because the migration must reach the network to fetch the tarball.

## Flagged ambiguities

- **"Migration"** is overloaded in the tree. The `migration_source/`, `pifinder_post_update.sh`, and `PiFinder_data/migrations/` machinery are **post-update actions** (per-version Raspberry Pi OS fixups), *not* this context. Reserve capital-M **Migration** for the OS-level in-place conversion; say **post-update actions** for the rest.
- **Tarball vs image.** `pifinder-migration-vX.Y.Z.tar.zst` (**migration tarball**, unpacked in place by an existing device) and `pifinder-vX.Y.Z.img.zst` (**SD image**, flashed onto a blank card) are different artifacts with different jobs. Never call the tarball "the image".
- **The 7× SQUARE gesture** means two different things on two different screens: on the Raspberry Pi OS Software screen it is **migration enable**; on the NixOS update screen it reveals the **unstable** update channel. They share only the gesture.
- **"Migrate the WiFi"** is a sub-step of the larger event — the init script rewriting `wpa_supplicant` entries into NetworkManager keyfiles, part of **preserved data**. Don't let it stand in for the whole **in-place migration**.

## Example dialogue

> **Dev:** A user on 2.6.0 wants NixOS but the update screen shows nothing. Bug?
>
> **Domain:** Expected. The **migration gate** is still closed, so nobody's offered it automatically yet. They can opt in per-device with **migration enable** — 7× SQUARE on the Software screen — if their PiFinder passes **pre-flight checks**.
>
> **Dev:** What if it's a Pi 3 or the card's been repartitioned?
>
> **Domain:** Pre-flight blocks it. It's all-or-nothing: wrong model, too little RAM, a non-stock partition layout, WiFi not in **Client mode**, or an unsupported display all stop the migration before anything is touched.
>
> **Dev:** And once it starts — do they lose their observations and WiFi?
>
> **Domain:** No. Both are **preserved data**: staged to RAM by the **migration initramfs**, then written back after the card is reformatted and the **migration tarball** is unpacked. WiFi credentials are rewritten as NetworkManager keyfiles on the way.
>
> **Dev:** Can they go back to Raspberry Pi OS if they don't like it?
>
> **Domain:** Not from inside the product — the migration is one-way. Recovery means reflashing a card from an **image build** (or their own backup). After migration the device is a NixOS PiFinder and updates through the **NixOS** context's **system update** channels from then on.
