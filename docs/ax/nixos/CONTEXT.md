# NixOS

How a NixOS PiFinder system is built, published, and updated over the air — the binary cache, the release/channel metadata, and the on-device upgrade flow. Distinct from the Raspbian→NixOS one-time **Migration**, which this context feeds but does not own.

## Language

### Repositories and their roles

**Upstream**:
The canonical public PiFinder repo, `brickbots/PiFinder`. The to-be home of releases, update channels, and (eventually) build infrastructure. On-device update channels already read from here (the **update manifest** on the `nixos-manifest` branch).
_Avoid_: "the main repo", bare "brickbots" in prose, "official".

**Fork**:
`mrosseel/PiFinder` (git remote `origin`). Where NixOS is developed (the `nixos` branch) and, through the transition, where every NixOS artifact is produced — CI builds, the Attic cache, the update manifest, release tags, and the migration tarball.
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

The on-device UI offers three update **channels**, each mapped to one stage of the branch promotion flow (testable PRs → `main` → `release`). Choosing a channel and a version resolves through the **update manifest** to a store path and installs it.

**stable**:
The production channel — official release entries in the generated manifest. The default for ordinary users.
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

**Watchdog**:
The on-device boot guardian. It health-checks every boot of a not-yet-**confirmed** generation (a **trial**) and performs a **generation rollback** when the trial fails — capturing evidence and telling the operator on screen. It never rolls back a confirmed generation, but it still *reports*: a confirmed generation whose app fails gets an on-screen advisory naming the **recovery hold** (see [NixOS ADR 0005](./adr/0005-self-arming-watchdog-confirmed-generations.md)).

**Trial**:
The probation boot of a generation that has not yet proven itself on this device. Every boot of an unconfirmed generation is a trial, regardless of which build installed it. A passed trial **confirms** the generation.
_Avoid_: "first boot" as a synonym — a trial can recur (e.g. after a crash before the health check completed).

**Health check**:
What a trial must pass: the app *itself* declares that its UI is live (readiness announced from the first drawn frame), and then stays up briefly. A merely-running process is not healthy — a build that starts but never turns the screen on must fail its trial. Outside supervised boots (development runs), the readiness announcement is a harmless no-op.
_Avoid_: equating "healthy" with "the service started".

**Confirmed generation**:
A generation that has passed a trial on this device, recorded locally. Confirmed generations are never auto-rolled-back — later failures are for the user-driven recovery ladder (Rollback channel, **recovery hold**, SSH), not the watchdog.
_Avoid_: "committed" (overloaded with VCS meaning).

**Recovery hold**:
The user gesture that enters **recovery mode**: hold the square-equivalent input while powering on, and keep holding until RECOVERY appears. Detected only during a short boot window (so it can never fire mid-observation). Deliberately a single input: v4's joystick makes multi-key chords physically impossible, and a square-equivalent will always exist.
_Avoid_: "recovery chord" (one input, not a chord).

**Recovery mode**:
The interactive rescue environment the **recovery hold** boots into: the update screen alone (no camera/solver/positioning), offering the local generation overview — marking the generation that was about to boot and each **confirmed generation** — plus the normal internet channels. Choosing a generation is *sticky* (it becomes the boot default); an internet pick installs through the ordinary upgrade flow and faces a **trial** like any install. If recovery mode itself fails its **health check**, the device falls back to a blind **generation rollback** to the newest confirmed generation. Never touches user data.
_Avoid_: "safe mode" (nothing about the broken build is run "safely" — recovery either works or falls through), "factory reset" (nothing is wiped).

**Generation rollback**:
The instance-local revert to an earlier NixOS generation. Triggered automatically by the **watchdog** when a **trial** fails, or manually. Bounded — local generations are pruned to three (the running one plus two rollback targets, surfaced in the Software screen's Rollback channel).

**Reinstall an older build**:
The durable rollback path: pick a prior version and install it — the device substitutes its prebuilt closure (it never compiles; the upgrade is `nix build … --max-jobs 0`), so the only requirement is that the closure still lives in a reachable cache. For **stable** and **beta** that is guaranteed (their closures live in the never-GC'd `pifinder-release` cache), so any past release reinstalls forever; **unstable** closures may be GC'd from the short-retention cache, at which point that exact build is un-installable until CI rebuilds and re-pushes it. Survives generation pruning and covers boots-but-misbehaves bugs the watchdog cannot catch.

**Yank**:
A release-level rollback — demoting a buggy official Release (to draft/prerelease, or superseding it) so it leaves the **stable** channel for *new* installs. There is no fleet-wide auto-revert: a device already on a yanked build surfaces an **advisory** (a status/notification that its version is withdrawn) prompting the user to choose the latest, who then recovers by **reinstalling an older build**. User-initiated, never automatic.

### Build and cache

**Attic cache**:
The binary cache at `cache.pifinder.eu`, with two namespaces: `pifinder` (dev builds, short retention) and `pifinder-release` (tagged releases, GC-disabled). Every Pi substitutes signed store paths from here. Hosted on the Fork's side through Phase 1.
_Avoid_: "cachix" (an earlier/alternative cache; the current one is Attic — see [NixOS ADR 0001](./adr/0001-attic-binary-cache.md)).

**pi5 runner**:
The self-hosted aarch64 GitHub Actions runner that builds NixOS systems natively, with a hosted `ubuntu-*-arm` runner (also native aarch64 — no emulation) as fallback. Fork-side infrastructure through Phase 1.

**Update manifest**:
`update-manifest.json` — the generated channel listing published on a metadata-only branch (`nixos-manifest` during the fork transition). It maps releases, trunk builds, and testable PR builds to signed Nix `store_path`s in the Attic cache (and, for releases, to the migration tarball). The device reads this raw JSON file instead of calling the GitHub API; it is the single mapping between versions and store paths.
_Avoid_: bare "manifest" (say *update* manifest), "build stamp" (a retired concept: `pifinder-build.json` is gone — a device's identity lives in one file, seeded at image build and rewritten by every upgrade).
