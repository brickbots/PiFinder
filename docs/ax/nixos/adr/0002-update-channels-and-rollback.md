# Update channels stay Release-based (stable/beta) over a live main+PR unstable; rollback via reinstall + passive yank

> **Corrected 2026-08:** only **stable** is pushed to the retained `pifinder-release` cache. `release.yml` sends **beta** to the finite-retention `pifinder` cache "so prereleases stay transient", so beta's rollback is durable only while its closure survives GC. The cache argument in the rejected `main`-head option below therefore no longer distinguishes beta from a continuous channel; what still does is the curation symmetry with stable (notes, explicit semver, the version gate).

The three on-device update **channels** map onto the git promotion flow (testable PRs → `main` → `release`) and resolve through a **build stamp** (`pifinder-build.json`) to a store path: **stable** = official GitHub Releases (non-prerelease, `≥ MIN_NIXOS_VERSION`); **beta** = GitHub **prereleases** cut from `main`; **unstable** = the live `main`/trunk head plus open `testable`-labeled PRs (the `main` entry rendered more prominently than the PR rows). stable and beta are ceremonial Releases — both curated (notes, explicit semver, the version gate); stable is pushed to the *retained* cache and beta to the short-retention one. unstable tracks ref heads continuously and is hidden until unlocked.

A bad build is recovered three ways, never by fleet-wide auto-revert: the **watchdog** reverts to the previous NixOS generation on a boot failure (once); a user can **reinstall any older build** by selecting it (the device only substitutes the prebuilt closure — `nix build … --max-jobs 0`, it never compiles); and a bad official release is **yanked** (demoted/superseded so it leaves the channel for new installs) plus a device **advisory** prompting affected units to choose the latest.

## Considered options

- **beta = live `main` head (continuous), rejected.** Briefly chosen, then reverted: GitHub's prerelease flag is built in and keeps beta symmetric with stable (notes, semver, gate). Decisively, a prerelease lands in the *retained* `pifinder-release` cache, so beta gets durable rollback; a `main`-head beta would sit in the short-retention cache and lose it. Continuous "every merge" delivery is unstable's job — `main` head lives there — not beta's.
- **Fully uniform branch-head channels (stable = `release` head), rejected.** Drops release notes, explicit versioning, the gate, and the SD-image/migration assets, and would need `build.yml` to stamp `release`.
- **Active kill-switch for yank, rejected for now.** Passive yank + advisory avoids a server-side bad-builds list and device polling/auto-revert; revisit only if the field shows the "already-running unit that never opens the update screen" gap is real.

## Consequences

- **Rollback is guaranteed for stable** — its closures live in the never-GC'd `pifinder-release` cache ([0001](./0001-attic-binary-cache.md)), and the device never builds. **beta**, **unstable** (`main`-head / PR) closures share the short-retention cache: they may be GC'd and become un-installable until CI rebuilds and re-pushes them. Beta keeps the rest of a Release's ceremony (notes, semver, gate, a durable GitHub Release record with its migration asset), just not the durable closure.
- Channel *sourcing* matches the current code. The cosmetic delta is done — `software.py` renders the trunk row bold and distinct from the PR rows. Still transitional: the unstable trunk is read from the `nixos` branch (`source_ref == "nixos"`) rather than `main`, until the NixOS line becomes mainline.
