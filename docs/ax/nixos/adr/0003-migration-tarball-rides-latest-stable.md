# Migration tarball resolves its full system from the update manifest at first boot (rides latest stable), instead of pinning a closure

> **Amended by [0004](./0004-migration-tarball-published-per-release.md):** publication is a per-(pre)release asset, not a built-once file. The resolve-at-first-boot mechanism below is unchanged.

The migration tarball is the **minimal** bootable system; on first boot it downloads the **full** PiFinder system from the binary cache and switches to it. We will have first-boot resolve that store path from the **same update manifest the on-device updater reads** (`brickbots/PiFinder@nixos-manifest:update-manifest.json`, see [0002](./0002-update-channels-and-rollback.md)) — taking the newest entry in the best available channel, **stable → beta → unstable trunk** — rather than baking a fixed store path into the tarball. Because **stable** holds only Releases, whose closures live in the never-GC'd `pifinder-release` cache ([0001](./0001-attic-binary-cache.md)), a resolved stable path can't be garbage-collected out from under a published tarball. The tarball therefore never goes stale, is built **once** (not per Release), and every new migrator gets the *current* system rather than the snapshot the tarball was cut from.

The trap this avoids: a baked/pinned closure couples the tarball's lifetime (months — until the next cut) to a single cache entry's lifetime. Pin into the short-retention `pifinder` cache and the closure is GC'd while the tarball is still the published download → first-boot fails. Pin into the retained `pifinder-release` cache and every intermediate test build piles up there forever (it is never GC'd) → the retained cache fills with dead closures, the exact thing "persist only the last version" is meant to prevent. Resolving *latest stable* at boot escapes both horns: nothing per-tarball is pinned, test churn stays in the self-cleaning unstable cache, and the only durable closures are deliberate Releases.

## Considered options

- **Bake the full closure into the tarball (self-contained), rejected.** Drops the cache dependency entirely and can never rot, but bloats the download (full system vs minimal) and freezes the migrated version to the tarball's build date. Resolving latest-stable keeps the tarball minimal and current.
- **Bake a pinned store path + push it to `pifinder-release`, rejected.** Durable, but every iteration pushes another full closure into the never-GC'd cache, and the tarball must be rebuilt and re-uploaded every Release. Directly conflicts with "only the last version persists."
- **Bake a pinned store path served from the short-retention `pifinder` cache, rejected.** Small and self-cleaning, but the pinned closure is GC'd (~90 days) and the still-published tarball breaks.

## Consequences

- First-boot reads the **update manifest**, not `pifinder-build.json` (which it previously fetched from `mrosseel/PiFinder@nixos`). First-boot and the updater now share one source of truth.
- Resolution order is **stable → beta → unstable trunk → baked-in `first-boot-target`**. The baked-in path survives only as a last-ditch fallback when the manifest can't be fetched.
- **Transitional:** with `stable`/`beta` empty until the first Release is cut, migration currently resolves the **unstable trunk**, which is the **`nixos` branch** (`source_ref == "nixos"`), not `main` — the NixOS line isn't upstream yet ([0002](./0002-update-channels-and-rollback.md)). Drop the `source_ref == "nixos"` guard once `nixos` becomes the mainline trunk.
- The tarball is built **once** and only rebuilt when the minimal migration system itself changes — never per Release. A "cut stable release" flow (build full system → push closure to `pifinder-release` → stamp a `stable` entry) is what makes new closures reachable; the tarball just rides whatever that produces.
