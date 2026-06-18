# NixOS Release Process

How PiFinder NixOS builds are versioned, published, and updated on devices.

> Not to be confused with the repo-root `RELEASE.md`, which is hand-written release notes for a specific version. This file documents the plumbing.

## Single source of truth

```
pifinder-build.json  (committed to the branch, repo root)
    │
    ├─ "version":    "3.0.0"        ← what the device displays
    └─ "store_path": "/nix/store/…" ← what the channel checker installs
```

Everything downstream reads this file. The Nix build copies it through verbatim. Nothing else writes it except CI (see below).

At runtime, `python/PiFinder/utils.py::get_version()` reads the JSON from `/home/pifinder/PiFinder/pifinder-build.json` — a symlink (`nixos/services.nix`) to the `pifinder-src` Nix store path, which contains the same file the source tree had when it was built.

## Artifacts

| Artifact                       | Where                             | Purpose                                |
| ------------------------------ | --------------------------------- | -------------------------------------- |
| Release closure on Attic       | `cache.pifinder.eu/pifinder-release` | What the device upgrade pulls (retained) |
| `pifinder-build.json` (git)    | repo root, committed              | Tells the channel checker what's live  |
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

## Who writes `pifinder-build.json`

```
┌──────────────────────────────────────────────────────────────────┐
│ CI dev build  (.github/workflows/build.yml :: stamp-build)       │
│   After every successful build on any branch, commits:           │
│     PR  → { "version": "PR#<n>-<sha>", "store_path": "<attic>" } │
│     else→ { "version": "<branch>-<sha>", "store_path": "<attic>"}│
│   Creates a "chore: stamp build [skip ci]" commit on the branch. │
├──────────────────────────────────────────────────────────────────┤
│ Release workflow  (.github/workflows/release.yml)                │
│   workflow_dispatch with `version: 3.0.0`. Stamps the JSON,      │
│   tags v3.0.0 (or v3.0.0-beta), publishes the GitHub Release.    │
└──────────────────────────────────────────────────────────────────┘
```

That's it. The Nix derivation reads the file but never writes it.

## Update channels

`python/PiFinder/ui/software.py` (Software-update menu) discovers what to offer:

| Channel | Source                                                                 |
| ------- | ---------------------------------------------------------------------- |
| stable  | GitHub Releases (non-prerelease, version ≥ `MIN_NIXOS_VERSION`)        |
| beta    | GitHub Pre-releases (version ≥ `MIN_NIXOS_VERSION`)                    |
| nightly | `raw.githubusercontent.com/.../<branch>/pifinder-build.json`           |

For each candidate, it reads `version` (to display) and `store_path` (to install). `MIN_NIXOS_VERSION = "2.5.0"` is hard-coded in `software.py:29`.

## Release flow

```
  workflow_dispatch (Release)
    inputs: version=3.0.0, type=stable|beta, source_branch=main, notes=…
        │
        ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ 1. checkout source_branch                                   │
  │ 2. write pifinder-build.json:                               │
  │      { "version": "3.0.0", "store_path": "" }               │
  │ 3. nix build .#…toplevel              → store path A        │
  │      (JSON inside A: version=3.0.0, store_path="")          │
  │ 4. nix build .#images.pifinder        → SD image embedding A│
  │ 5. extract migration tarball from SD image                  │
  │ 6. attic push A → pifinder-release (retained)              │
  │ 7. rewrite pifinder-build.json:                             │
  │      { "version": "3.0.0", "store_path": "A" }              │
  │ 8. git commit + push + tag v3.0.0 (or v3.0.0-beta)          │
  │ 9. create GitHub Release with SD image + tarball            │
  └─────────────────────────────────────────────────────────────┘
```

SD image, tarball, Attic (`pifinder-release`) closure, and committed JSON all agree on store path A. Devices display `3.0.0`. Channel checker sees `3.0.0` pointing at A.

## Dev build flow

```
  push to any branch
        │
        ▼
  ┌─────────────────────────────────────────┐
  │ build.yml                               │
  │   1. nix build closure (native + emulated) │
  │   2. attic push → pifinder (dev cache)  │
  │   3. stamp-build job:                   │
  │        version = "<branch>-<sha>"       │
  │        write + commit pifinder-build.json │
  │        "chore: stamp build [skip ci]"   │
  │   4. (nixos branch only) build migration tarball, │
  │      upload to GitHub Release           │
  └─────────────────────────────────────────┘
```

A device built at commit X reports the version from commit X-1's stamp (the previous CI run). One-commit lag for the display string. Channels see the freshest stamp.

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
6. If the release should force-deprecate older clients, bump `MIN_NIXOS_VERSION` in `python/PiFinder/ui/software.py` in a follow-up commit.

## Hotfix release

Use `source_branch=release/X.Y` (long-lived hotfix branches). The release workflow stamps and tags on that branch, leaving `main` untouched.

## Files of interest

| File                                  | Role                                       |
| ------------------------------------- | ------------------------------------------ |
| `pifinder-build.json`                 | The single committed JSON, repo root       |
| `python/PiFinder/utils.py`            | `get_version()` reader                     |
| `python/PiFinder/ui/software.py`      | Channel update UI + `MIN_NIXOS_VERSION`    |
| `nixos/pkgs/pifinder-src.nix`         | Copies the JSON through into the store path |
| `nixos/services.nix`                  | Symlinks `/home/pifinder/PiFinder` → store path |
| `nixos/migration.nix`                 | `BUILD_JSON_URL` for nightly channel check |
| `.github/workflows/build.yml`         | Dev builds + nightly stamp                 |
| `.github/workflows/release.yml`       | Manual release dispatcher                  |
