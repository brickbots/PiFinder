# Self-hosted Attic for NixOS binary distribution

A NixOS PiFinder runs from pre-built binaries in `/nix/store/`; updates work by
atomically swapping the running system for a new closure of pre-built binaries.
Distributing those binaries requires a **binary cache** — a server that hands
them out on demand, since recompiling from source on a Pi is not viable (Rust
crates alone take hours). We will self-host the [Attic](https://github.com/zhaofengli/attic)
binary cache at `cache.pifinder.eu`, backed by SQLite and local disk initially,
with Cloudflare R2 as the eventual chunk store. Attic is a small Rust server
that adds **content-defined chunking (FastCDC)** on top of the standard Nix
substituter protocol: every NAR is sliced into variable-size chunks by byte
content and identical chunks are stored exactly once. This dedup is
**server-side** — it shrinks storage across releases, and because `attic push`
chunks on the runner it makes the **CI upload** proportional to actual changes.
It does **not** delta the device download: Attic serves whole NARs over the
standard binary-cache protocol, so a device fetches the full (compressed) NAR of
every store path whose hash changed — not a chunk-delta against the previous
version of that path. The saving devices get is **path-level**: the 90–95% of a
closure that is unchanged between releases (identical store hashes) is not
refetched at all, so an update pulls only the changed paths' NARs — on the order
of tens of MB for a 1.5 GB closure, but each of those in full. True client-side
chunk-delta downloads need a casync/desync-style client that keeps a local chunk
store; the standard Nix client — and therefore Attic, harmonia, and nix-casync
used as substituters — does not do this. (That client-delta property is exactly
why desync is used for the out-of-closure astro-data blobs; see the data-blob
distribution notes.)

## Considered Options

- **Stay on cachix.org indefinitely.** Rejected: SaaS quota caps (storage tier,
  push throttling) become a planning concern as the system closure grows; ships
  full NARs per closure (no chunking), so every update transfers the full
  closure even when 5% of bytes changed; per-cache pricing scales linearly with
  closure count.
- **Magic Nix Cache (DetSys) alone.** Rejected: backed by GitHub Actions Cache
  (~10 GB per repo, ephemeral, HTTP-418 rate-limited under sustained traffic —
  already broke a `type-check` job once). Useful for CI runner-local caching,
  not for distributing binaries to end-user devices, which it cannot do at all.
- **nix-casync.** Same content-defined-chunking idea, predates Attic, but
  distributed as a standalone tool rather than a hosted server; would need to
  assemble the server side ourselves. Attic delivers the same dedup story as a
  complete package.
- **harmonia.** Newer self-hosted alternative; simpler than Attic but no
  chunking. Loses the headline bandwidth-and-storage saving.

## Consequences

- **Operational ownership:** PiFinder takes on a small piece of infrastructure
  (one VPS, one Rust binary, one SQLite file, one Caddy reverse-proxy with
  Let's Encrypt). Sized at Hetzner CX22 / €4 month for the foreseeable future;
  SQLite handles millions of chunks before PostgreSQL becomes necessary. Backup
  story is "snapshot the SQLite file and the chunk directory" — same pattern as
  a typical small VPS service.
- **Egress economics:** Cloudflare R2 charges zero egress, which matters when
  distributing updates to a globally-dispersed PiFinder fleet. Self-hosted on a
  Hetzner VPS the egress is also effectively free at typical hobby volumes.
  Either way, the bandwidth question stops being a recurring concern.
- **CI publish step:** `build.yml`'s `cachix-action` step is replaced by an
  `attic push` step using a long-lived JWT minted by `atticadm make-token
  --push pifinder`, stored as `secrets.ATTIC_TOKEN`. Chunking happens on the
  runner; the server only ingests new chunks. Push payload is proportional to
  actual changes, not to closure size.
- **Device pull side:** `services.nix` declares `cache.pifinder.eu` as a
  substituter alongside `cache.nixos.org`, with the Attic public key in
  `trusted-public-keys`. The existing on-device upgrade flow
  (`pifinder-upgrade.service`, `nix build "$STORE_PATH" --max-jobs 0`) is
  unchanged — the new substituter is transparent. Users see the same
  "downloading N/M" progress in the menu, just with smaller N.
- **Failure model:** Nix tries substituters in order and falls through. If
  `cache.pifinder.eu` is unreachable, the device falls through to
  `cache.nixos.org` for any path that exists there. The "Attic outage = bricked
  PiFinders" scenario does not exist for paths nixpkgs already publishes; only
  locally-built paths (kernel with our overlays, `cedar-detect-server`, Python
  wheels) are at risk during an outage, and those are cached locally on devices
  that previously updated successfully.
- **Migration tarball stays self-contained.** The boot-from-tarball path
  (`pifinder-nixos-v3.0.0.tar.zst` on the GitHub release) is independent of the
  cache and remains the way a stock Debian PiFinder bootstraps into NixOS. A
  later refinement could ship a smaller tarball that pulls the bulk of the
  closure from Attic on first boot, but that is out of scope for this ADR.
- **No retirement of cachix.org is mandated here.** Whether to keep cachix.org
  as a fallback or drop it after Attic is proven is a separate operational
  decision; the substituter list can carry both indefinitely with no penalty
  beyond the cachix subscription cost.
- **Two caches, split by retention.** The server hosts two Attic caches:
  `pifinder` (dev/nightly builds from `build.yml`, short retention — these churn
  on every push) and `pifinder-release` (tagged release closures from
  `release.yml`, garbage collection disabled). The split exists because Attic
  retention is per-cache, not per-path: a device may upgrade to a release months
  after it was cut, so its closure must never be GC'd, while dev builds should
  not accumulate forever. Chunk dedup is global across caches on the same
  server, so storing a release closure separately costs only its genuinely-new
  chunks. Each cache has its own signing key; devices trust both, plus
  `cache.nixos.org`. (Originally a single `pifinder` cache; this followed once
  releases started flowing through Attic instead of cachix.)
