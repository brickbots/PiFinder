# NixOS builds come from a self-hosted Attic cache; the Pi installs them through three update channels

A NixOS PiFinder runs only prebuilt store paths. It never compiles: a build on a Pi takes hours, and Rust crates alone are too slow. So CI builds every system, and the Pi downloads it from a binary cache.

**Cache.** We host the [Attic](https://github.com/zhaofengli/attic) cache at `cache.pifinder.eu`. It has two caches with different retention:

- `pifinder`: CI builds, PR builds and beta prereleases. Old paths are garbage-collected.
- `pifinder-release`: stable releases. Garbage collection is off, so a release stays installable for ever.

Each cache has its own signing key. The Pi trusts both keys and `cache.nixos.org`. Attic stores each NAR as FastCDC chunks and keeps each chunk once, across both caches. This makes the storage and the CI upload small. Attic serves whole NARs to the Nix client, so the Pi does not get chunk deltas from Attic itself. [ADR 0036](./0036-delta-updates-on-demand-differ.md) adds deltas for system paths, and [ADR 0040](./0040-data-packs.md) adds chunk transfer for data packs.

**Channels.** The Pi offers three channels. Each resolves through the update manifest (`update-manifest.json` on the `nixos-manifest` branch) to a store path:

- **stable:** official GitHub Releases, not prereleases, from the version gate on. Pushed to `pifinder-release`.
- **beta:** GitHub prereleases cut from `main`. Curated like stable (notes, semver, version gate), but pushed to `pifinder`, so a beta is installable only while its closure is not garbage-collected.
- **unstable:** the trunk head plus open PRs with the `testable` label. The trunk row shows in bold. Until the NixOS line is mainline, the trunk is the `nixos` branch of the fork (`source_ref == "nixos"`).

The Pi installs a pick with `nix build <store path> --max-jobs 0`, so it downloads and never builds.

**Recovery from a bad build.** There is no fleet-wide automatic revert. A bad build is recovered in three ways:

1. The boot watchdog rolls back a generation that fails its first boots ([ADR 0038](./0038-boot-watchdog-and-recovery.md)).
2. The user reinstalls an older build from its channel. For stable this always works.
3. A bad release is yanked: it is demoted or superseded, so new installs do not get it. A Pi that runs it shows an advisory.

## Considered options

- **Stay on cachix.org, rejected.** Quota limits, and no chunk dedup, so the cost grows with each closure.
- **Magic Nix Cache alone, rejected.** It is a CI cache in GitHub Actions storage. It cannot serve devices.
- **nix-casync, rejected.** The same chunk idea, but a tool, not a complete server.
- **harmonia, rejected.** Simpler, but without chunk dedup.
- **beta as the live `main` head, rejected.** GitHub prereleases keep beta curated like stable. Continuous delivery is the job of unstable.
- **stable as the `release` branch head, rejected.** It loses release notes, versions, the version gate and the release assets.
- **An active kill switch for yanked builds, rejected for now.** A passive yank plus an advisory needs no server list and no polling.

## Consequences

- We operate one small server: Attic (one Rust binary, SQLite, local disk, Caddy with Let's Encrypt). Backup is a snapshot of the SQLite file and the chunk directory.
- CI pushes with `attic push` and a long-lived token (`secrets.ATTIC_TOKEN`). The upload holds only new chunks.
- If `cache.pifinder.eu` is down, the Pi still gets every path that `cache.nixos.org` has. Only our own paths (patched kernel, `cedar-detect-server`, Python packages) wait for our cache.
- Rollback by reinstall is guaranteed only for stable. beta and unstable closures can be garbage-collected, and then that build cannot install until CI pushes it again.
- The update manifest is the single mapping from versions to store paths. The first boot after the migration reads it too ([ADR 0039](./0039-card-layout-and-migration.md)).

Replaces NixOS ADR 0001 (Attic cache) and 0002 (update channels and rollback).
