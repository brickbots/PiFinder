# NixOS Handover

Current state as of `2026-06-24`:

- Latest pushed commit on `mrosseel/PiFinder:nixos` is `210f2c08` (`feat(nixos): drive update channels from manifest`).
- The branch is clean locally in the current worktree.
- GitHub Actions run `28119693140` is in progress for that push.

## What changed

- The PiFinder software UI no longer queries the GitHub REST API at runtime.
- Device channel data now comes from one generated raw JSON file:
  - `https://raw.githubusercontent.com/mrosseel/PiFinder/nixos-manifest/update-manifest.json`
- The manifest contains:
  - stable release entries
  - beta prerelease entries
  - unstable trunk + testable PR entries
- Old stamp-commit behavior on the source branch was removed.
- CI now updates the metadata-only `nixos-manifest` branch instead of committing `pifinder-build.json` back onto `nixos`.

## Important files

- [`python/PiFinder/ui/software.py`](../../python/PiFinder/ui/software.py)
- [`python/tests/test_software.py`](../../python/tests/test_software.py)
- [`.github/scripts/update_manifest.py`](../../.github/scripts/update_manifest.py)
- [`.github/workflows/build.yml`](../../.github/workflows/build.yml)
- [`.github/workflows/release.yml`](../../.github/workflows/release.yml)
- [`docs/ax/nixos/CONTEXT.md`](./CONTEXT.md)
- [`nixos/RELEASE.md`](../../nixos/RELEASE.md)

## Verified locally

- `nix develop path:. -c bash -lc 'cd python && pytest -m unit tests/test_software.py -q'`
- `nix develop path:. -c bash -lc 'cd python && mypy PiFinder/ui/software.py'`
- `python3 -m py_compile .github/scripts/update_manifest.py`

The focused software tests pass in the Nix Python 3.13 environment.

## Device state

- On the real PiFinder, `/home/pifinder/PiFinder` is a root-owned symlink into `/nix/store`.
- The running `pifinder.service` uses the store-backed source tree, not writable local source.
- `/var/lib/pifinder/current-build.json` reflects the installed build after updates.

## Current risk

- The manifest workflow is new and needs CI confirmation.
- Build-native and update-manifest passed in CI on the last run before this handover.
- Release workflow still writes a temporary `pifinder-build.json` in the workspace for build stamping inside the job, but it no longer commits that file back to the source branch.

## If you continue

1. Watch run `28119693140` to completion.
2. Verify `nixos-manifest` exists and contains `update-manifest.json`.
3. If CI fails, look first at the `update-manifest` job and the release workflow step that pushes the metadata branch.
4. If the device still shows no PRs, inspect the manifest contents, not the GitHub API, because runtime no longer calls GitHub REST.
