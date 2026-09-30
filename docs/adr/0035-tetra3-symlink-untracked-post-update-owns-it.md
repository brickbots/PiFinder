# The tetra3 symlink is untracked, post-update owns it, and a failed update says so

`python/tetra3` — the symlink through which `import tetra3` resolves the
solver package — is deliberately **not tracked in git**. It is gitignored and
created by every path that materialises a working tree: `pifinder_setup.sh`
on install, `pifinder_post_update.sh` on every update (which also moves any
impostor at that path aside), and the CI workflows after checkout.
`pifinder_update.sh` checks `git pull`'s exit status and reports failure
instead of unconditionally printing "update complete".

(ADR 0034 is reserved by the in-flight CM4 `gpio-poweroff` record, PR #639.)

## Context

Fielded units stopped being able to update past v2.5.1, silently. The chain:

- Since the Cedar switch, the solver lives in the `python/PiFinder/tetra3`
  submodule; the importable package is its inner `tetra3/tetra3/` dir. With
  the app run from `python/`, `import tetra3` resolves the *package* through
  the `python/tetra3` symlink; the `sys.path.append(utils.tetra3_dir)` in
  `solver.py` exposes the package's *contents* as top-level modules
  (`cedar_detect_pb2` and friends) — without the symlink, that same append
  makes `import tetra3` find the inner `tetra3.py` module instead of the
  package, which fails on its first package-relative import. The symlink is
  load-bearing wherever the app or tests run.
- `migration_source/v2.1.0.sh` created `python/tetra3` on every updated unit
  with a bare `ln -s` to an **absolute** path. On 2.2.2-era cards where a
  plain tetra3 folder already sat at that path, `ln -s` silently dropped the
  link *inside* the folder instead of replacing it.
- Commit `0a8262fa` (first shipped in v2.6.0) started **tracking** the
  symlink, as a **relative** link, so submodule CI could import tetra3.
- `git pull` refuses to write a tracked path over any untracked file — even a
  byte-identical symlink (verified empirically; the refusal is path-level,
  not content-level). So on every unit upgraded in place — absolute symlink
  from the migration, or plain folder from the 2.2.2 era — the pull to
  ≥ v2.6.0 aborts with "untracked working tree files would be overwritten".
  Only fresh clones and fresh SD images, where the path was empty or already
  the tracked link, updated cleanly.
- `pifinder_update.sh` ignored the pull's exit code, sourced the (old)
  post-update script anyway, and printed "PiFinder software update complete".
  Every menu attempt looked like a success while changing nothing.

The trap in fixing it: a stuck unit runs its **old** copy of
`pifinder_update.sh`, so no new pre-pull guard can reach it through the menu.
The only code from the new release that a stuck unit executes is
`pifinder_post_update.sh` — which the old script sources *after* the pull,
freshly read from disk — and only if the pull succeeds. Therefore the pull
has to succeed first, which means git must stop needing to write
`python/tetra3` at all.

## Decision

1. **Untrack `python/tetra3`** (`git rm --cached`, plus a `.gitignore` entry).
   Once the release tree no longer contains the path, `git pull` never
   touches it, and whatever a unit has on disk there cannot block the update.
2. **`pifinder_post_update.sh` owns the symlink.** On every update it moves
   anything at `python/tetra3` that is not the relative link
   `PiFinder/tetra3/tetra3` aside to `/home/pifinder/tetra3_old_<timestamp>`
   (kept, not deleted) and (re)creates the link. The `ln -s` in
   `migration_source/v2.1.0.sh` is deleted — it produced the absolute links.
3. **`pifinder_update.sh` fails honestly.** A failed `git pull` prints
   "update FAILED", leaves the old version in place, and exits non-zero;
   `sys_utils.update_software()` catches the non-zero exit and returns
   `False`, which lights up the UI's existing (previously unreachable)
   "Error on Upd" branch instead of "Ok! Restarting".

The rescue path for a stuck unit is then one ordinary menu update: the old
script's pull succeeds against the new tree, the old script sources the *new*
post-update from disk, and the repair block replaces the leftover folder or
absolute link. No SSH required.

## Considered options

- **Keep the symlink tracked; add a pre-pull guard to `pifinder_update.sh`.**
  Rejected: the guard ships inside the very update the stuck units cannot
  take. It would protect the future fleet only, and every currently stuck
  unit would still need the manual SSH fix (`mv python/tetra3 ~/tetra3_old`).
- **Keep the symlink tracked; fix units by hand over SSH.** Works — it is how
  the first affected user was unblocked — but the population is "every unit
  upgraded in place since the Cedar switch", not a handful, and each one
  fails silently until its owner reports it.
- **Track the symlink but also ship it in the SD image.** Does nothing for
  the collision: git's refusal is path-level, so even units whose on-disk
  link exactly matches the tracked blob fail the pull.

## Consequences

- **Fresh clones and worktrees have no `python/tetra3` until something
  creates it.** The app and any test that imports the solver need it, so:
  `pifinder_setup.sh` creates it on install, `nox.yml` and
  `web-integration-tests.yml` create it after checkout, and a developer
  setting up a clone or worktree creates it by hand
  (`ln -s PiFinder/tetra3/tetra3 python/tetra3`, per `CLAUDE.md`). mypy and
  ruff exclude the path, so they don't care either way.
- **Units currently on v2.6.x lose the tracked link during the pull** (their
  tree drops the path) and get it back from the repair block moments later
  in the same run.
- **The repair is unconditional, not a one-shot migration**, so any future
  corruption of the link self-heals on the next update, and re-running an
  update is always safe. The moved-aside copies accumulate under
  `/home/pifinder/tetra3_old_<timestamp>` at most once per corruption, not
  per run.
- **Re-tracking `python/tetra3` would reintroduce the whole failure** for
  every unit in the field. The `.gitignore` entry and this record are the
  guard rails.
