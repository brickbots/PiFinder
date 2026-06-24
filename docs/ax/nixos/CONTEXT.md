# NixOS

How a NixOS PiFinder system is built, published, and updated over the air — the binary cache, the release/channel metadata, and the on-device upgrade flow. Distinct from the Raspbian→NixOS one-time **Migration**, which this context feeds but does not own.

## Language

### Repositories and their roles

**Upstream**:
The canonical public PiFinder repo, `brickbots/PiFinder`. The to-be home of releases, update channels, and (eventually) build infrastructure. On-device update channels already read from here (`software.py` `GITHUB_REPO`).
_Avoid_: "the main repo", bare "brickbots" in prose, "official".

**Fork**:
`mrosseel/PiFinder` (git remote `origin`). Where NixOS is developed (the `nixos` branch) and, through the transition, where every NixOS artifact is produced — CI builds, the Attic cache, build stamping, release tags, and the migration tarball.
_Avoid_: "my repo", bare "mrosseel", "the staging repo" used interchangeably with branch names.

**Trunk**:
The branch that holds the live NixOS development tip and feeds the "unstable" channel's non-PR entry. Today that is `nixos` **on the Fork**; in the steady state it is `main` on the Upstream. The branch is a single switch (`TRUNK_BRANCH`), not hard-coded to `main`.
_Avoid_: conflating "trunk" with the literal branch name `main`.

### Transition

**Phase 1**:
Release/channel metadata and the migration gate live on the **Upstream**; the **Attic cache** and the **pi5 runner** (build infrastructure) stay on the **Fork**. A Pi reads release metadata from the Upstream but substitutes store paths from the Fork's cache.

**Phase 2**:
Everything — builds, cache, releases, channels — is hosted by the **Upstream**. The Fork reverts to an ordinary contributor fork.

**In-between phase**:
The current state: no NixOS artifacts exist on the Upstream yet (PR #379 not merged), so all three channels are temporarily sourced from the **Fork** (its releases for stable/beta, its `nixos` trunk + testable PRs for unstable) via a single switch, purely so they can be exercised for testing. Reverts to Upstream/`main` at upstreaming.

### Channels

The on-device UI offers three update **channels**, each mapped to one stage of the branch promotion flow (testable PRs → `main` → `release`). Choosing a channel and a version resolves to a **Build stamp** and installs that store path.

**stable**:
The production channel — official GitHub Releases (non-prerelease), cut from the `release` branch and gated at `MIN_NIXOS_VERSION`. The default for ordinary users.
_Avoid_: "release channel" (the *branch* is `release`; the *channel* is "stable").

**beta**:
The integration channel — GitHub **prereleases** (the `prerelease` flag), cut deliberately from `main`. Curated like stable (notes, explicit semver `vX.Y.Z-beta`, the version gate) and pushed to the *retained* cache, so beta builds reinstall durably too. Ceremonial, not continuous.
_Avoid_: naming the channel "prerelease" — it is "beta"; prerelease is its mechanism.

**unstable**:
The bleeding-edge channel — the live `main`/**trunk** head plus open PRs carrying the `testable` label, each installable at its own head. The `main` entry is rendered more prominently to set it apart from the per-PR rows. Hidden until unlocked (7× square).
_Avoid_: "preview", "nightly".

**As-is vs to-be:** channel *sourcing* matches the current code (stable/beta = Releases split on the prerelease flag; unstable = `main` head + testable PRs). The only deltas are cosmetic and transitional: render the unstable `main` entry more prominently than PR rows, and — until upstreaming — read from the Fork's `nixos` trunk (see In-between phase).

### Rollback

**Rollback**:
Returning a device — or the fleet — to a known-good build after a bad one ships. Guaranteed for **stable** and **beta** — both are Releases whose closures live in the retained `pifinder-release` cache; only **unstable** (`main` head / PR) builds may be GC'd from the short-retention dev cache.

**Generation rollback**:
The instance-local revert to the previous NixOS generation. Triggered automatically by the **watchdog** on a boot failure (once), or manually. Bounded — local generations are pruned to two, so it reaches only one step back.

**Reinstall an older build**:
The durable rollback path: pick a prior version and install it — the device substitutes its prebuilt closure (it never compiles; the upgrade is `nix build … --max-jobs 0`), so the only requirement is that the closure still lives in a reachable cache. For **stable** and **beta** that is guaranteed (their closures live in the never-GC'd `pifinder-release` cache), so any past release reinstalls forever; **unstable** closures may be GC'd from the short-retention cache, at which point that exact build is un-installable until CI rebuilds and re-pushes it. Survives generation pruning and covers boots-but-misbehaves bugs the watchdog cannot catch.

**Yank**:
A release-level rollback — demoting a buggy official Release (to draft/prerelease, or superseding it) so it leaves the **stable** channel for *new* installs. There is no fleet-wide auto-revert: a device already on a yanked build surfaces an **advisory** (a status/notification that its version is withdrawn) prompting the user to choose the latest, who then recovers by **reinstalling an older build**. User-initiated, never automatic.

### Build and cache

**Attic cache**:
The binary cache at `cache.pifinder.eu`, with two namespaces: `pifinder` (dev builds, short retention) and `pifinder-release` (tagged releases, GC-disabled). Every Pi substitutes signed store paths from here. Hosted on the Fork's side through Phase 1.
_Avoid_: "cachix" (an earlier/alternative cache; the current one is Attic — see [NixOS ADR 0001](./adr/0001-attic-binary-cache.md)).

**pi5 runner**:
The self-hosted aarch64 GitHub Actions runner that builds NixOS systems natively, with a hosted `ubuntu-*-arm` QEMU fallback. Fork-side infrastructure through Phase 1.

**Build stamp**:
`pifinder-build.json` — the file CI commits to a branch (or a release tags) mapping a git ref to a signed Nix `store_path` in the Attic cache. The on-device channels resolve a chosen version to an installable path by reading this file.
_Avoid_: "manifest", "build manifest".
