# NixOS Release Process

How PiFinder NixOS builds are versioned, published, and updated on devices.

> Not to be confused with the repo-root `RELEASE.md`, which is hand-written release notes for a specific version. This file documents the plumbing.

## Single Source Of Truth

```
update-manifest.json  (committed to the metadata-only nixos-manifest branch)
    │
    └─ channels[]
        ├─ "version":    "3.0.0"        ← what the device displays
        └─ "store_path": "/nix/store/…" ← what the device installs
```

Source branches stay source-only. CI writes generated install metadata to the
manifest branch after successful builds and releases. The device fetches the raw
manifest JSON; it does not call the GitHub API and it does not probe branch-head
`pifinder-build.json` files.

At runtime, `python/PiFinder/utils.py::get_version()` reads
`/var/lib/pifinder/current-build.json` — the device's single identity file.
The image builder seeds it with the system's own store path; the updater
rewrites it (with version/label/channel) on every install. Human version
labels come from the update manifest, which maps store paths to versions.
(`pifinder-build.json` is retired.)

## Artifacts

| Artifact                       | Where                             | Purpose                                |
| ------------------------------ | --------------------------------- | -------------------------------------- |
| Release closure on Attic       | `cache.pifinder.eu/pifinder-release` | What the device upgrade pulls (retained) |
| `update-manifest.json`         | `nixos-manifest` branch           | Tells the channel checker what's live  |
| Git tag `vX.Y.Z`               | GitHub                            | Marks a release commit                 |
| GitHub Release                 | GitHub Releases                   | Carries the SD image + tarball         |
| `pifinder-vX.Y.Z.img.zst`      | GitHub Release asset              | SD card image for fresh installs       |
| `pifinder-migration-vX.Y.Z.tar.zst` | GitHub Release asset         | Tarball for in-place migration         |

## Binary caches

Two self-hosted Attic caches on `cache.pifinder.eu` (ADR 0004):

| Cache              | Pushed by                  | Retention        | Holds                          |
| ------------------ | -------------------------- | ---------------- | ------------------------------ |
| `pifinder-release` | `release.yml`              | never GC'd       | tagged release closures        |
| `pifinder`         | `build.yml`                | short (dev GC)   | dev + nightly branch builds    |

Release closures go to `pifinder-release` so a device upgrading long after a
release still resolves the store path; dev builds churn through `pifinder`.
Devices subscribe to both (`nixos/services.nix`), release cache first, with
`cache.nixos.org` as the fall-through for upstream paths. `cachix.org` is no
longer used.

Both caches are declared server-side in nixos-config
(`machines/general-server/attic-service.nix`). To prune the dev cache later, set
retention **per-cache** (`attic cache configure local:pifinder --retention-period
<N>`), never globally — a global retention would also evict `pifinder-release`.

## Who Writes `update-manifest.json`

```
┌──────────────────────────────────────────────────────────────────┐
│ CI dev build  (.github/workflows/build.yml :: update-manifest)   │
│   After a successful build, commits to nixos-manifest only:       │
│     PR  → channel=unstable, kind=pr, store_path=<attic>          │
│     else→ channel=unstable, kind=trunk, store_path=<attic>       │
├──────────────────────────────────────────────────────────────────┤
│ Release workflow  (.github/workflows/release.yml)                │
│   workflow_dispatch with `version: 3.0.0`. Builds, tags,         │
│   publishes the GitHub Release, then updates stable/beta in the  │
│   manifest branch.                                               │
└──────────────────────────────────────────────────────────────────┘
```

That's it. Generated metadata never lands on the source branch.

## Update channels

`python/PiFinder/ui/software.py` (Software-update menu) discovers what to offer:

| Channel | Source                                                                 |
| ------- | ---------------------------------------------------------------------- |
| stable   | `update-manifest.json` release entries (`kind=release`)               |
| beta     | `update-manifest.json` prerelease entries (`kind=release`)            |
| unstable | `update-manifest.json` trunk + PR entries                             |

For each candidate, it reads `version` (to display) and `store_path` (to
install). Entries with `available=false` or invalid store paths are visible but
not installable.

## Release flow

```
  workflow_dispatch (Release)
    inputs: version=3.0.0, type=stable|beta, source_branch=main, notes=…
        │
        ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ 1. checkout source_branch                                   │
  │ 2. nix build .#…toplevel              → store path A        │
  │ 3. nix build .#images.pifinder        → SD image embedding A│
  │      (image seeds /var/lib/pifinder/current-build.json      │
  │       with store path A; labels resolve via the manifest)   │
  │ 5. extract migration tarball from SD image                  │
  │ 6. attic push A → pifinder-release (retained)              │
  │ 7. tag v3.0.0 (or v3.0.0-beta)                              │
  │ 8. create GitHub Release with SD image + tarball             │
  │ 9. update nixos-manifest with store_path A                   │
  └─────────────────────────────────────────────────────────────┘
```

SD image, tarball, Attic (`pifinder-release`) closure, and manifest entry all
agree on store path A. Devices display `3.0.0`. Channel checker sees `3.0.0`
pointing at A.

## Dev build flow

```
  push / testable PR build
        │
        ▼
  ┌─────────────────────────────────────────┐
  │ build.yml                               │
  │   1. nix build closure (native + emulated) │
  │   2. attic push → pifinder (dev cache)  │
  │   3. update-manifest job:               │
  │        version = "<branch>-<sha>" or PR │
  │        commit update-manifest.json only │
  │        on nixos-manifest                │
  │   4. (nixos branch only) build migration tarball, │
  │      upload to GitHub Release           │
  └─────────────────────────────────────────┘
```

A device installed from the manifest reports the exact manifest version selected.
There is no one-commit lag and no source-branch stamp commit.

## Cutting a release

1. Make sure `source_branch` (usually `main` or `nixos`) is at the commit you want to release.
2. GitHub → Actions → **Release** → Run workflow.
3. Inputs:
   - `version`: semver only, no `v` prefix — e.g. `3.0.0`
   - `notes`: markdown body for the GitHub Release
   - `type`: `stable` or `beta` (beta tags as `vX.Y.Z-beta` and marks the release as prerelease)
   - `source_branch`: branch to release from (default `main`)
4. Workflow runs end-to-end (~30–45 min).
5. Verify the GitHub Release has both `pifinder-vX.Y.Z.img.zst` and `pifinder-migration-vX.Y.Z.tar.zst`.
6. If the release should hide older entries, update the manifest generator policy
   or prune the manifest branch in a follow-up change.

## Hotfix release

Use `source_branch=release/X.Y` (long-lived hotfix branches). The release
workflow builds and tags that source branch, then writes install metadata to
`nixos-manifest`.

## Files of interest

| File                                  | Role                                       |
| ------------------------------------- | ------------------------------------------ |
| `.github/scripts/update_manifest.py`  | Manifest merge/update helper               |
| `update-manifest.json`                | Generated JSON on `nixos-manifest`         |
| `python/PiFinder/utils.py`            | `get_version()` reader                     |
| `python/PiFinder/ui/software.py`      | Manifest-driven channel update UI          |
| `nixos/pkgs/pifinder-src.nix`         | Copies the source tree into the store path |
| `nixos/services.nix`                  | Symlinks `/home/pifinder/PiFinder` → store path |
| `nixos/device.nix`                 | `BUILD_JSON_URL` for nightly channel check |
| `.github/workflows/build.yml`         | Dev builds + manifest update               |
| `.github/workflows/release.yml`       | Manual release dispatcher                  |
