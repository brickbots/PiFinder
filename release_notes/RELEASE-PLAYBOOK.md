# PiFinder release playbook

The reusable process behind a release. The per-release artifacts (`release_notes/X.Y.Z.md`,
`release-X.Y.Z-test-plan.md`) stay one-off documents; this file is what you read before
writing them, so the same handful of things don't get rediscovered every cut.

Draft status: sections marked TODO are gaps I couldn't answer from the repo or from our
previous sessions. Everything else is checked against what actually happened in 2.6.1 and
2.6.3, and against `main` on 2026-11-16.

## Two tracks, one repo

**Track A, the 2.x line.** This is the shipping product. Devices run Raspberry Pi OS and
update in place with `git pull` on the `release` branch. `ui/software.py` fetches
`https://raw.githubusercontent.com/brickbots/PiFinder/release/version.txt`, compares it to
the local version with `update_needed()`, and only then offers the update. Nothing about
this line is automated: the merge, the tag, the GitHub release and the SD image are all
done by hand.

**Track B, the 3.x NixOS line.** Released by the "Release NixOS image" workflow
(`.github/workflows/release.yml`, `workflow_dispatch`). Its process, rules and known faults
are written down in `nixos/RELEASE.md`, which lives on the `nixos` branch of
`mrosseel/PiFinder` until #379 merges. This playbook points at that file and does not
restate it. The first draft of this playbook did restate it, and four of those statements
were wrong ten weeks later.

Most of the playbook is Track A. Say which track you're cutting before you start, because the
answer changes who creates the tag.

The two tracks meet in the migration: from 2.6.4 on, every 2.x release carries the code that
moves a unit to NixOS. See "Where the tracks meet" below.

## Branch model

`main` is integration. `release` is production. Code moves main into release at the cut, never
the other way. Feature branches PR into `main`.

The cut is a merge, not a fast-forward, whenever `release` carries a commit `main` doesn't.
It always does by now: every earlier cut and every docs promotion left a merge commit there.
That is fine as long as the merge is clean and its tree equals `main`'s. Check before you
promise anyone a clean cut:

```bash
git fetch origin
git merge-tree --write-tree origin/release origin/main; echo "exit=$?"
git rev-parse 'origin/main^{tree}'
git rev-list --count origin/release..origin/main                # what's shipping
```

Exit 0 means a clean merge, exit 1 means conflicts, and the conflicted files are listed. The
first line of the output is the tree the merge would produce. It should equal `main`'s tree
on the next line. That way testing `main` is testing the cut.

Don't count conflict markers in that output. An earlier version of this file piped it into
`grep -c '<<<<<<<'`. The command prints a tree id and a file list, never markers, so the grep
says 0 on a conflicted merge. It says 0 on the 2.6.3 cut, which had a conflict.

When the only conflict is `version.txt`, resolve it to the new version and confirm the
resolved tree equals `main`'s. That was the 2.6.3 cut: `release` carried `b485e3be`, the
commit that paused 2.6.2 by reverting `version.txt`. Don't rebase or force-push `release` to
tidy history away.

### Between cuts, promoting docs

Read the Docs builds `/en/release/` from the `release` branch. A docs fix merged to `main`
is invisible to readers until it reaches `release`. Promote it out of cycle by merging `main`
into `release`, with no tag and no `version.txt` change, under one condition:

```bash
git diff --stat origin/main origin/release    # must be empty BEFORE the docs fix merged
```

If the trees already matched, the promotion carries only the new commits. If they didn't, the
promotion is a partial release cut: cherry-pick the docs commits, or wait for the real cut.

A promotion moves everything on `main`, not only docs. #639 and #640 are code, and they
reached `release` this way after the `v2.6.3` tag. A unit that updated later, or a fresh
install, has them. No unit on 2.6.3 was ever offered them, because `version.txt` didn't
change. So "2.6.3" in the field is two trees: the tag, and the later `release` tip. Upgrade
gates for the next cut cover both.

Don't commit to `release` directly. The case fix of 2026-10-23 went onto both branches as
two separate commits. It merges clean only because the files are identical.

## Phase 1, prep on main

Open a draft PR against `main` carrying the release notes and the test plan. 2.6.3 did this as
PR #636 in a worktree named `release-X.Y.Z-prep`.

- [ ] Pick the version number. Skipping one is fine and sometimes right: 2.6.2 was cut for
      internal rev4 units and never went public, so 2.6.3 folded it in rather than reusing the
      number. Record the reason in the notes.
- [ ] Establish the range. Diff the last public tag against `main`, not the last cut and not
      the `release` tip: `git log --oneline v2.6.3..origin/main`. The field population is on
      the last public release, so anything internal or promoted since is still new to them.
- [ ] Write `release_notes/X.Y.Z.md`. Long form, the reference document. Lead with an "after
      you update" section covering anything that changes under the user without being asked:
      changed defaults, rescaled readings, renamed labels, retroactive data changes.
- [ ] Write `release-X.Y.Z-test-plan.md`. Risk-ordered, not feature-ordered. Each gate gets an
      owner, a pass criterion, and a note on what a failure blocks. See the gate structure below.
- [ ] Note which items are *carried* from a previous plan rather than re-derived. The 2.6.3
      plan carried the whole optics tranche from 2.6.2 and said so.
- [ ] Add the previous release's docs snapshot to the "previous versions" notes (phase 5).

## Phase 2, pre-flight on main

This is the part that has actually bitten us. Work through it before the merge.

- [ ] **`version.txt` on `main` reads the new version, and it's committed.** For 2.6.2 the bump
      existed only as an uncommitted working-copy edit. Cutting like that means no device is ever
      offered the update, and the screen just says "No Update needed" forever. Highest-leverage
      item on this list precisely because it looks done.
- [ ] `update_needed()` opens the gate from every population in the field, not just the newest.
      2.6.3 had to satisfy both 2.6.1 devices and internal 2.6.2 ones.
- [ ] Merge shape verified with `git merge-tree --write-tree` (above).
- [ ] Know what the cut does to `.github/`: `git diff --stat origin/release origin/main -- .github/`.
      A difference is not a failure, it is part of what ships. What matters is which copy a
      hand-started workflow runs. While `release` is the GitHub default branch, the Actions
      page and `gh workflow run` use the `release` copy unless you name a ref. Until the 2.6.4
      cut, that copy of `release.yml` is the old one. It writes `migration_url` to the update
      manifest, which is the key 2.6.1 to 2.6.3 read. Those versions then run their old ext4
      migration on a btrfs tarball, and the card does not boot. That happened to a test card
      in October. Until the cut, start that workflow with `--ref main` only.
- [ ] `migration_gate.json` on `main` reads what you intend to ship. Until the gate is opened
      on purpose, that is both flags `false`.
- [ ] ADR ledger has no duplicate numbers. Gaps are expected: 0036 to 0045 are taken on the
      NixOS line, so check the next free number against both `main` and the `nixos` branch.
      Recompute the free slot at merge time and never trust a written-down reservation; they
      went stale twice during the 2.6.3 cycle.
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
| 1 | Automated: ruff lint + format, mypy, smoke + unit + UI tests, sphinx `-nW`, i18n | CI or dev box, ~15 min |
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

- [ ] Merge `main` into `release`, resolve `version.txt` to the new version if it conflicts,
      verify the tree matches `main`.
- [ ] Push `release`. The moment this lands, every device that checks for updates is offered
      the new version. There is no staged rollout.
- [ ] Tag it. **Tag the commit `release` pointed at when the update opened**, and do it at the
      cut rather than later. We've been inconsistent here: `v2.6.1` is on `8c6ae841`, which sits
      on both branches, but `v2.6.3` ended up on `31c900c3`, two commits past the actual release
      merge, because the tag went on afterwards. That makes "what shipped as 2.6.3" ambiguous.
- [ ] Push the tag.

Tag by hand for Track A only. Expect to see NixOS tags on this branch all the same:
`v3.1.1-beta` to `v3.1.3-beta` sit on `release` commits, and `v3.1.3-beta` is on the case fix.
Those betas were built from `mrosseel/PiFinder`. Before #708 (2026-11-22) the workflow tagged the
source commit only when the source was this repo, and the release step then created the tag on
the default branch. So `git describe` on `release` names a 3.x beta. That is noise, not a
release of that commit. Since #708 a build from the fork tags the commit it built, through the
API (a fork shares its objects with this repo). If that step fails it only warns, and the old
behaviour returns, so check where a new 3.x tag points.

## Phase 5, snapshot the docs

Every release gets a docs build frozen at its own URL, so a user on an old version reads the
manual that matches their device.

We used to do this, stopped, and resumed with 2.6.3. `pifinder.readthedocs.io` serves
`v1.11.2`, `v2.0.4`, `v2.1.1` and `v2.6.3`. Nothing exists for 2.2 through 2.6.1, so anyone on
2.4 hitting `/en/release/` today reads rev4 docs describing hardware and menus they don't have.

The mechanism is Read the Docs building a version per git tag. That's where `/en/v2.1.1/` came
from, and `/en/v3_hardware/` (referenced as `|v3_docs|` in `docs/source/conf.py`) is the same
trick applied to the pre-rev4 manual. No branch, no repo change, one dashboard action.

- [ ] Once the tag from phase 4 is pushed, open the Read the Docs dashboard, find the new
      version under Versions, and set it Active.
- [ ] Confirm the build succeeds and `https://pifinder.readthedocs.io/en/vX.Y.Z/` resolves.
- [ ] Activate only the `vX.Y.Z` tags you pushed for Track A. The `v3.x-beta` tags point at
      Pi OS commits (phase 4), so a build of one is the 2.x manual under a 3.x name.
- [ ] The "previous versions" note in `docs/source/index.rst`, `docs/source/user_guide.rst`
      and `docs/source/quick_start.rst` can only link a snapshot that already exists. So each
      prep PR adds the *previous* release's snapshot and drops the oldest entry. This was
      skipped for 2.6.3: the notes still list only 1.x, 2.0.x and 2.1.x. The 2.6.4 prep adds
      `/en/v2.6.3/`. Those three notes are hand-maintained duplicates of each other, so all
      three or none.
- [ ] Leave `/en/release/` as the URL everything links to. It follows the `release` branch and
      is what the update instructions in the GitHub release body point at. It is also in the
      web interface of every unit (`python/views/base.html`), so it has to resolve for ever.
- [ ] Bump `min_software` in `docs/source/conf.py` if the manual has stopped describing older
      software.

Since the tag is what RTD builds from, phase 4's rule about tagging the actual release commit
matters here too. A tag two commits past the cut produces a docs snapshot that never shipped.

We are not backfilling 2.2 through 2.6.1. The gap stays; the note just needs to stop implying
otherwise (see one-time tasks).

## Phase 6, build and publish the image

TODO. The GitHub release for 2.6.3 points at
`https://ddbeeedxfpnp0.cloudfront.net/software/PiFinder_2.6.3.img`, so the 2.x image is built
and uploaded outside this repo. Nothing here describes how. Needs: how the image is built, what
gets baked in (preconfigured hardware settings were documented in #637), how it's uploaded, and
whether anything verifies the upload before the release body links to it. Write this section
while doing it for 2.6.4.

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
- [ ] Every place the cut deviated from this file becomes an edit to this file.
- [ ] Watch for field reports before starting the next tranche. Docs fixes between cuts go
      through `main` and a promotion (see "Between cuts").

## Track B, the NixOS release

Read `nixos/RELEASE.md` on the `nixos` branch of `mrosseel/PiFinder`. It is the process, and
it is kept current by the people who run it. What a Track A release manager needs from it:

- The workflow creates the tag and the GitHub release. Don't tag a 3.x release by hand.
- Start the workflow from a ref that has the current `release.yml`. Since #658 that is `main`.
  It is not the default ref until the 2.6.4 cut (phase 2).
- A beta goes to a cache that deletes it after 90 days. A stable release is kept for ever.
- Devices find a release through `update-manifest.json` on the `nixos-manifest` branch.

## Where the tracks meet, the migration

2.6.4 is the first Pi OS release that can migrate a unit to NixOS (#657). From it on, a 2.x
cut is also a release of the migration, so these belong to Track A.

**The contract freezes when the release ships.** A unit on 2.6.4 reads the gate from
`migration_gate.json` on `release` (flag `nixos_migration`), finds its target in the update
manifest (keys `migration_v2_url` and `migration_v2_sha256_url`, lists read in the order
stable, beta, unstable), and expects one tarball layout. None of that can change for units
on 2.6.4 after they have it. A change needs a new 2.x release that reads a new key.
`nixos/RELEASE.md` holds the exact list. Read it before the cut, not after.

**Two names stay dead for ever.** 2.6.3 and older read the flag `nixos_for_everyone` and the
manifest key `migration_url`, and then run an ext4 migration. Keep the flag `false` and never
write the key.

**Seven presses of SQUARE ignore the gate.** On the Software screen of 2.6.4 they offer the
first available manifest entry that has a tarball, gate open or closed. So the migration is
reachable the day 2.6.4 ships. Gate 3 of a 2.x test plan therefore includes a real migration
from a card on that version: one Pi 4 unit and one rev4 (CM4) unit. On rev4, also power on,
reboot and power off afterwards. GPIO14 is the power-off line there, and one byte on the
serial port cuts the power.

**Betas expire.** While the manifest has only betas, keep one that is newer than 90 days.
After that the cache has deleted the system, and a migration fails at its first NixOS boot.

**Opening the gate is a release.** It is a one-line change to `migration_gate.json` on
`release`, and it gets the same care as a cut:

- [ ] A stable NixOS release is in the manifest. Not only betas.
- [ ] A Pi 4 unit and a rev4 unit migrated on hardware, from a card on the current 2.x.
- [ ] The announcement is written, and it says what a user keeps and what they must do.
- [ ] The change goes through `main` and a promotion when the trees match. If they don't, it
      is the one case for a pull request straight to `release`.

One consequence to plan around. With the gate open, the Software screen on 2.6.4 or later
offers the migration before it reads `version.txt`, and it never shows a release version. A
later 2.x release cannot be offered in the app to those units while the gate is open. Units
on 2.6.3 or older still read `version.txt`, so they update to the newest 2.x first and migrate
second. This is from reading `ui/software.py`; nobody has tried it on a device yet. If a 2.x
hotfix is needed after the gate opens, close the gate first.

### Decided for 2.6.4 (2026-11-16)

- #697, the rebuilt catalog database, ships in 2.6.4. The cut waits for its on-device
  checklist.
- No stable NixOS release before the 2.6.4 cut. The gate stays closed and both flags stay
  `false`. Seven presses of SQUARE land on a beta, so the 90-day rule above applies from day
  one. `v3.1.3-beta` was built on 2026-11-11.

## The `release` branch after NixOS, a transition plan

Proposed 2026-11-16. Nothing here has been done yet.

`release` does four jobs today. Only the first is tied to the branch name. The plan keeps
that one for ever and moves the other three away, each at its own moment.

| Job `release` does today | Tied to the name? | Plan | When |
|---|---|---|---|
| What Pi OS units pull: code, `version.txt`, `migration_gate.json` | Yes | Keep, for as long as one Pi OS unit exists | Never changes |
| GitHub default branch | No | Move the default to `main` | Step 1, after the 2.6.4 cut |
| Target of the `main` into `release` cut | No | Hotfixes only, by pull request to `release` | Step 2, when #379 merges |
| Published docs at `/en/release/` | The URL is, the branch is not | Redirect to `/en/stable/` | Step 3, first stable 3.x |

Why the first job can't move: `pifinder_update.sh` runs `git checkout release`, and
`ui/software.py` reads `version.txt` and `migration_gate.json` from that branch by URL. Both
are on every unit in the field, and a unit runs its old copy to fetch the new one.

### Step 1, default branch to `main`

When: right after the 2.6.4 cut. The two branches hold the same tree then, so a visitor to
the repo sees no change.

Safe because nothing depends on the default: `pifinder_setup.sh` clones with
`--branch release`, the update script names the branch, and so do the URLs.

- [ ] Confirm `git diff --stat origin/main origin/release` is empty.
- [ ] Change the default branch in the GitHub repository settings.
- [ ] In each clone: `git remote set-head origin -a`.
- [ ] Remove the two notes in `CLAUDE.md` that tell agents to distrust the detected main
      branch and to re-root worktrees.
- [ ] Delete `ci/btrfs-migration-release` once `nixos/RELEASE.md` starts releases from `main`.

What it fixes: a hand-started workflow uses `main`'s copy without being told, `Closes #NNN`
closes the issue when the pull request merges, and new pull requests open against `main`.

### Step 2, `release` becomes the Pi OS maintenance branch

When: the day #379 (NixOS support) merges into `main`. That merge ends the Track A cut. On the
`nixos` branch `python/requirements.txt` and `migration_gate.json` do not exist, and
`ui/software.py` is the NixOS upgrade screen. Merge that into `release` and the update script
fails at `pip install -r`, and every 2.6.4 unit reads a missing gate file as a closed gate.

So hold #379 until Pi OS can live on hotfixes. While Pi OS is the shipping product, the
current arrangement is the cheap one: the `nixos` branch merges `main` regularly, and Pi OS
gets every fix by the normal cut. After #379, each Pi OS fix is a hand-made backport. Until
then, keep landing the parts of the `nixos` branch that are plain app code on `main` as their
own pull requests, the way #657 and #658 landed, so the final merge is small.

- [ ] Make the last normal cut from `main` before #379 merges.
- [ ] Protect `release`: no merges from `main`, changes by pull request only.
- [ ] A Pi OS hotfix is a pull request against `release`, with its own `version.txt` bump and
      its own tag on `release`. Phases 2 to 4 of this file shrink to that.
- [ ] Rewrite the branch model in `CLAUDE.md`, which today forbids pull requests to `release`.
- [ ] Move `nixos/RELEASE.md` under this file's Track B, or point each at the other.
- [ ] Check that the newest 3.x tag is on the NixOS source commit it was built from. #708
      makes that true for builds from the fork too; step 3 depends on it.

### Step 3, docs follow the product

When: the first stable 3.x release. Until then `/en/release/` is the right manual for almost
everyone, and it keeps building from `release`.

Read the Docs cannot point the `release` address at another branch. It does document this
way to retire a version:

- [ ] Activate the `stable` version. It is their built-in alias for the highest version tag
      that is not a pre-release, so it skips `v3.x-beta` tags and moves to each new stable
      release by itself.
- [ ] Check that `/en/stable/` shows the 3.x manual. It builds from the tag, so the tag must
      be on the NixOS source commit (step 2, last item; #708).
- [ ] Make `stable` the default version, so the bare address lands there.
- [ ] Deactivate the `release` version and add one exact redirect:
      `/en/release/*` to `/en/stable/:splat`. The redirect works only once the old version is
      off.
- [ ] Test `https://pifinder.readthedocs.io/en/release/user_guide.html#update-software` and
      the User Guide link in a unit's web interface.

The Pi OS manual stays available as the last `/en/v2.6.x/` snapshot from phase 5, and the
version note at the top of the 3.x manual links to it. A unit that has not migrated follows
its built-in link to the 3.x manual, so that note has to be easy to see.

Deep links survive because the page names are the same on both lines today. Keep them the
same: don't rename a docs page on the NixOS line without adding a redirect for it.

A manual pinned to a tag does not pick up docs fixes between releases. On NixOS a point
release is one workflow run, so that is the way to publish one.

### Not decided

- When Track A ends, meaning the last 2.x hotfix. `release` has to exist after that anyway,
  for the units that never update.
- Whether #379 merges before the first stable 3.x or with it. This plan works either way;
  the earlier it merges, the longer Pi OS runs on backports.

## Traps worth re-reading before every cut

1. `version.txt` bumped but not committed. Silent, total, and it looks done.
2. Re-tracking `python/tetra3`. Breaks `git pull` on every in-place-upgraded unit.
3. A migration script added but not registered in `pifinder_post_update.sh`.
4. New menu entries shifting menu indexes and breaking keypress-counting web tests.
5. Stale mypy cache reporting errors that aren't there.
6. Device left in a non-English language, failing web tests that assert English strings.
7. ADR number reservations going stale between writing and merging.
8. Tagging after the cut instead of at it.
9. Starting "Release NixOS image" from the default ref before the 2.6.4 cut. It writes the
   manifest key that 2.6.3 reads.
10. Counting conflict markers in `git merge-tree` output. It always says 0.
11. A docs promotion that also carries code. It ships to fresh installs with no version bump.

## One-time tasks, not yet done

- [x] Reword the "previous versions" note in `docs/source/index.rst`,
      `docs/source/user_guide.rst` and `docs/source/quick_start.rst`. It currently offers 1.x,
      2.0.x and 2.1.x as if that were the full set, which reads as coverage rather than a
      three-version archive. We're not backfilling 2.2 to 2.6.1, so the wording should say
      what it is. Do it in the 2.6.4 prep PR, together with adding `/en/v2.6.3/`.
- [ ] `nixos/RELEASE.md` on the `nixos` branch still starts releases from
      `ci/btrfs-migration-release`, lists the old workflow on `main` as a known fault (#658
      fixed it), says a release built from the fork makes no tag (since #708 it tags the built commit),
      and points at the root `RELEASE.md` this PR removes.
- [ ] `CONTEXT-MAP.md` on `main` links to `docs/ax/nixos/CONTEXT.md` and `docs/ax/nixos.md`.
      Both exist only on the `nixos` branch, so the links are dead until #379 or #497 lands.
- [x] Retire `RELEASE.md` at the repo root. Done 2026-09-05: it was a byte-identical copy of
      `release_notes/2.6.1.md` with nothing in the repo referencing it. `release_notes/X.Y.Z.md`
      has been the real home since 2.6.1, and there is now no root-level file claiming to
      describe the current release.

## Still open

- Phase 6 is a stub. How does the SD image get built, what goes into it, and how does it reach
  CloudFront?
- Phase 7's three announcement channels need their specifics filled in.
- The Software screen's behaviour with the gate open is read from code, not seen on a device.
- The two items under "Not decided" in the transition plan.
