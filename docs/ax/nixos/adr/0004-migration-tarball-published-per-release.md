# Migration tarball is published as a (pre)release asset, not a built-once file (amends 0003)

The tarball keeps [0003](./0003-migration-tarball-rides-latest-stable.md)'s *mechanism* — minimal system (`images.pifinder-migration`), full system resolved from the update manifest at first boot, so the tarball's content never goes stale — but its *publication* moves from "built once at a fixed URL" to an asset (with `.sha256` sidecar) on every stable/beta Release, referenced per-entry as `migration_url` in the manifest. Releases are visible, versioned, documented, and in the canonical place; a replace-in-place file on a private file server is none of those, and un-auditable after an incident.

## Considered options

- **Built-once evergreen tarball at a fixed URL (0003's original), rejected.** Minimal asset churn, but the artifact lives outside the release record: no version, no notes, no checksum ceremony, silent replace-in-place. The Raspbian-side updater would also need a hardcoded URL instead of reading the manifest like everything else.
- **Per-release *full-system* tarball (shipped briefly in the first release.yml), rejected.** ~1.4 GB per release forever, and it freezes the migrated system to the tarball's build date — the exact staleness trap 0003 exists to avoid.

## Consequences

- `release.yml` must tar `images.pifinder-migration`, **not** `images.pifinder` (the full SD image remains a separate asset for fresh flashes).
- Two-stage resolution: the Raspbian device picks a *tarball* (first manifest entry with a `migration_url`, stable → beta → unstable); first boot then picks the *closure* from the manifest — the authoritative version decision. Any reasonably recent tarball yields the same end state.
- Asset cost per release drops to the minimal system's size; old tarballs remain downloadable alongside their releases.
