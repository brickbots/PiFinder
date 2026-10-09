# PiFinder release playbook

The reusable process behind a release. The per-release artifacts (`release_notes/X.Y.Z.md`,
`release-X.Y.Z-test-plan.md`) stay one-off documents; this file is what you read before
writing them, so the same six things don't get rediscovered every cut.

Draft status: sections marked TODO are gaps I couldn't answer from the repo or from our
previous sessions. Everything else is checked against what actually happened in 2.6.1 and
2.6.3.

## Two tracks, one repo

**Track A, the 2.x line.** This is the shipping product. Devices run Raspberry Pi OS and
update in place with `git pull` on the `release` branch. `ui/software.py` fetches
`https://raw.githubusercontent.com/brickbots/PiFinder/release/version.txt`, compares it to
the local version with `update_needed()`, and only then offers the update. Nothing about
this line is automated: the merge, the tag, the GitHub release and the SD image are all
done by hand.

**Track B, the 3.x NixOS line.** `.github/workflows/release.yml` (workflow_dispatch, "Release
NixOS image") builds the SD image and migration tarball on an aarch64 runner, pushes the
closure to `cache.pifinder.eu`, tags the source commit, publishes a GitHub release with
`.img.zst` + `.tar.zst` + `.sha256` sidecars, and records the release in the `nixos-manifest`
branch. Devices only see it when `migration_gate.json` opens (`nixos_for_everyone`, currently
`false`). See the end of this file.

Most of the playbook is Track A. Say which track you're cutting before you start, because the
answer changes who creates the tag.

## Branch model

`main` is integration. `release` is production. Code moves main into release at the cut, never
the other way. Feature branches PR into `main`.

The cut is a merge, not a fast-forward, whenever `release` carries a commit `main` doesn't.
Right now it does, because of `b485e3be` (the 2.6.2 version.txt pause). Check before you
promise anyone a clean cut:

```bash
git fetch origin
git merge-tree origin/release origin/main | grep -c '<<<<<<<'   # conflict count
git rev-list --count origin/release..origin/main                # what's shipping
```

If the only conflict is `version.txt`, resolve it to the new version and confirm the resolved
tree equals `main`'s. That way testing `main` is testing the cut. Don't rebase or force-push
`release` to tidy history away.

## Phase 1, prep on main

Open a draft PR against `main` carrying the release notes and the test plan. 2.6.3 did this as
PR #636 in a worktree named `release-X.Y.Z-prep`.

- [ ] Pick the version number. Skipping one is fine and sometimes right: 2.6.2 was cut for
      internal rev4 units and never went public, so 2.6.3 folded it in rather than reusing the
      number. Record the reason in the notes.
- [ ] Establish the range. Diff the last public tag against `main`, not the last cut:
      `git log --oneline v2.6.1..origin/main`. The field population is on the last public
      release, so anything internal is still new to every user.
- [ ] Write `release_notes/X.Y.Z.md`. Long form, the reference document. Lead with an "after
      you update" section covering anything that changes under the user without being asked:
      changed defaults, rescaled readings, renamed labels, retroactive data changes.
- [ ] Write `release-X.Y.Z-test-plan.md`. Risk-ordered, not feature-ordered. Each gate gets an
      owner, a pass criterion, and a note on what a failure blocks. See the gate structure below.
- [ ] Note which items are *carried* from a previous plan rather than re-derived. The 2.6.3
      plan carried the whole optics tranche from 2.6.2 and said so.

## Phase 2, pre-flight on main

This is the part that has actually bitten us. Work through it before the merge.

- [ ] **`version.txt` on `main` reads the new version, and it's committed.** For 2.6.2 the bump
      existed only as an uncommitted working-copy edit. Cutting like that means no device is ever
      offered the update, and the screen just says "No Update needed" forever. Highest-leverage
      item on this list precisely because it looks done.
- [ ] `update_needed()` opens the gate from every population in the field, not just the newest.
      2.6.3 had to satisfy both 2.6.1 devices and internal 2.6.2 ones.
- [ ] Merge shape verified with `git merge-tree` (above).
- [ ] `.github/` byte-identical between `release` and `main`, so the workflows that run
      post-cut are the ones already exercised: `git diff origin/release origin/main -- .github/`
- [ ] ADR ledger clean. No duplicate numbers, no gaps. Recompute the free slot at merge time
      and never trust a written-down reservation; they went stale twice during the 2.6.3 cycle.
- [ ] i18n pass. `nox -s babel`, then confirm every catalog has 0 untranslated and 0 fuzzy, no
      msgid was removed, and each `.mo` is byte-identical to a fresh `pybabel compile`. Note
      `messages.pot` is gitignored, so scope the diff to the tracked `.po` files. New menu
      entries shift menu indexes and break Selenium tests that navigate by counting keypresses;
      that has happened twice.
- [ ] `default_config.json` diff since the last public tag. Every added key is a visible change
      on an untouched upgrade. List them in the notes.
- [ ] New migration needed? Add `migration_source/vX.Y.Z.sh` **and** register it in
      `pifinder_post_update.sh` with its own sentinel file under
      `~/PiFinder_data/migrations/`. An unregistered script never runs.
- [ ] `requirements.txt` / `requirements_dev.txt` / `noxfile.py` changes staged on the image if
      the SD image needs them baked in.
- [ ] `python/tetra3` is still untracked. Never re-track that symlink (ADR 0035). A tracked
      version makes `git pull` refuse to update every in-place-upgraded unit in the field.

## Phase 3, the gates

The plan's shape, reused across 2.6.1, 2.6.2 and 2.6.3. Gates 1 to 3 must pass before the
merge; 4 to 6 before the update is offered.

| Gate | What | Runs where |
|---|---|---|
| 1 | Automated: ruff lint + format, mypy, smoke + unit, sphinx `-nW`, i18n | CI or dev box, ~15 min |
| 2 | Bench on standard hardware, the population that upgrades | Real device |
| 3 | The release-specific risk. Whatever this cut could break that nothing else covers | Real device |
| 4 | Upgrade paths and fresh install, from every version still in the field | Real device |
| 5 | Under the stars | Real device |
| 6 | Web, API, planetarium protocols | Dev box + phone |

Baselines worth recording each time, because the trend catches regressions the suite doesn't:
smoke+unit count (1,238 at the 2.6.2 cut, 1,305 at #631, 1,531 at 2.6.3), msgid count
(694 × 4 catalogs at 2.6.3), sphinx page count.

Two automation traps: clear the mypy cache first (`rm -rf .mypy_cache`), because a stale cache
reports phantom errors. And reset `language` to `en` in `~/PiFinder_data/config.json` before the
web suite, because the tests assert English titles and a device left in Chinese fails three of
them for no reason.

## Phase 4, the cut

- [ ] Merge `main` into `release`, resolve `version.txt` to the new version, verify the tree
      matches `main`.
- [ ] Push `release`. The moment this lands, every device that checks for updates is offered
      the new version. There is no staged rollout.
- [ ] Tag it. **Tag the commit `release` pointed at when the update opened**, and do it at the
      cut rather than later. We've been inconsistent here: `v2.6.1` is on `8c6ae841`, which sits
      on both branches, but `v2.6.3` ended up on `31c900c3`, two commits past the actual release
      merge, because the tag went on afterwards. That makes "what shipped as 2.6.3" ambiguous.
- [ ] Push the tag.

## Phase 5, snapshot the docs

Every release gets a docs build frozen at its own URL, so a user on an old version reads the
manual that matches their device.

We used to do this and stopped. `pifinder.readthedocs.io` still serves `v1.11.2`, `v2.0.4` and
`v2.1.1`, and `index.rst`, `user_guide.rst` and `quick_start.rst` all link to them from the
"previous version" note. Nothing exists for 2.2 through 2.6, so anyone on 2.4 hitting
`/en/release/` today reads rev4 docs describing hardware and menus they don't have.

The mechanism is Read the Docs building a version per git tag. That's where `/en/v2.1.1/` came
from, and `/en/v3_hardware/` (referenced as `|v3_docs|` in `docs/source/conf.py`) is the same
trick applied to the pre-rev4 manual. No branch, no repo change, one dashboard action.

- [ ] Once the tag from phase 4 is pushed, open the Read the Docs dashboard, find the new
      version under Versions, and set it Active.
- [ ] Confirm the build succeeds and `https://pifinder.readthedocs.io/en/vX.Y.Z/` resolves.
      A failed build leaves a dead link in the version note.
- [ ] Add it to the "previous versions" note in `docs/source/index.rst`,
      `docs/source/user_guide.rst` and `docs/source/quick_start.rst`, and drop the oldest entry
      so the list doesn't grow forever. Those three notes are hand-maintained duplicates of
      each other, so all three or none.
- [ ] Leave `/en/release/` as the URL everything links to. It follows the `release` branch and
      is what the update instructions in the GitHub release body point at.
- [ ] Bump `min_software` in `docs/source/conf.py` if the manual has stopped describing older
      software.

Since the tag is what RTD builds from, phase 4's rule about tagging the actual release commit
matters here too. A tag two commits past the cut produces a docs snapshot that never shipped.

We are not backfilling 2.2 through 2.6. The gap stays; the note just needs to stop implying
otherwise (see one-time tasks).

## Phase 6, build and publish the image

TODO. The GitHub release for 2.6.3 points at
`https://ddbeeedxfpnp0.cloudfront.net/software/PiFinder_2.6.3.img`, so the 2.x image is built
and uploaded outside this repo. Nothing here describes how. Needs: how the image is built, what
gets baked in (preconfigured hardware settings were documented in #637), how it's uploaded, and
whether anything verifies the upload before the release body links to it.

## Phase 7, announce

- [ ] Draft the GitHub release body from `release_notes/X.Y.Z.md`. It's a much shorter document
      with a different voice, so write it fresh rather than trimming: check the last two or
      three releases and match them. Both 2.6.1 and 2.6.3 did this as an explicit pass, with
      the output staged in a scratch file first.
- [ ] Body includes the image URL and a link to the update instructions
      (`https://pifinder.readthedocs.io/en/release/user_guide.html#update-software`).
- [ ] If a version was skipped, say so plainly near the top and say why.
- [ ] Publish the GitHub release against the tag.
- [ ] Post to Discord. TODO: which channel, and whether it's the full GitHub body or a shorter
      note with a link.
- [ ] Post to the Cloudy Nights thread. TODO: thread URL, and whether it's a new post or a
      reply on the standing thread.
- [ ] Email owners. TODO: where the list lives, who sends it, and what it contains beyond a
      link. This one reaches people who never check GitHub, so it probably deserves the
      "after you update" section verbatim rather than a link.

Order matters a little: publish the GitHub release first, since the other three link to it.

## Phase 8, after

- [ ] Carry open review findings forward into the next cycle's notes rather than letting them
      die with the plan. The Focus exposure hold lease fix and the stale `camera_lens` on
      camera-type switch have both survived two releases this way.
- [ ] Update the release memory file so the next cut starts from the real branch state.
- [ ] Watch for field reports before starting the next tranche. The `release` branch takes
      direct doc fixes between cuts (#638, #639, #640, #641 all landed straight on it).

## Track B, the NixOS release

Run the "Release NixOS image" workflow (`workflow_dispatch`) with version, notes, type
(stable or beta), and source branch. Notes on it:

- Stable pushes the closure to the retained `pifinder-release` Attic cache; beta goes to the
  finite-retention `pifinder` cache. Getting this backwards means devices can't resolve the
  closure months later.
- The migration tarball is cut from the minimal migration system, not the full image, and has a
  hard 800 MB budget. The workflow fails the release above it. That guard exists because of the
  2026-07-05 field failure: the tarball is copied into RAM during migration, and a 2 GB board
  only holds about 1.4 GB.
- The workflow creates the tag and the GitHub release itself, so don't tag by hand first.
- Devices discover the release through the `nixos-manifest` branch, and only when
  `migration_gate.json` says `nixos_for_everyone: true`.

## Traps worth re-reading before every cut

1. `version.txt` bumped but not committed. Silent, total, and it looks done.
2. Re-tracking `python/tetra3`. Breaks `git pull` on every in-place-upgraded unit.
3. A migration script added but not registered in `pifinder_post_update.sh`.
4. New menu entries shifting menu indexes and breaking keypress-counting web tests.
5. Stale mypy cache reporting errors that aren't there.
6. Device left in a non-English language, failing web tests that assert English strings.
7. ADR number reservations going stale between writing and merging.
8. Tagging after the cut instead of at it.

## One-time tasks, not yet done

- [ ] Reword the "previous versions" note in `docs/source/index.rst`,
      `docs/source/user_guide.rst` and `docs/source/quick_start.rst`. It currently offers 1.x,
      2.0.x and 2.1.x as if that were the full set, which reads as coverage rather than a
      three-version archive. We're not backfilling 2.2 to 2.6, so the wording should say what
      it is.
- [x] Retire `RELEASE.md` at the repo root. Done 2026-09-05: it was a byte-identical copy of
      `release_notes/2.6.1.md` with nothing in the repo referencing it. `release_notes/X.Y.Z.md`
      has been the real home since 2.6.1, and there is now no root-level file claiming to
      describe the current release.

## Still open

- Phase 6 is a stub. How does the SD image get built, what goes into it, and how does it reach
  CloudFront?
- Phase 7's three announcement channels need their specifics filled in.
