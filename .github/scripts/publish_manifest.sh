#!/usr/bin/env bash
# Publish update-manifest.json to the metadata-only `nixos-manifest` branch.
#
# Two invariants this enforces that a plain `checkout -B` + `add <file>` does not:
#   1. Single-file tree: the branch only ever holds update-manifest.json, never
#      the source tree it was forked from. `git add -A` over a pruned worktree
#      stages the deletions, so the committed tree collapses to one file even if
#      the remote tip was previously polluted.
#   2. Concurrency safety: a trunk build and a PR build can finish at once and
#      both rewrite the same file. A git ref update is compare-and-swap, so we
#      re-fetch, re-apply this run's single entry onto the new tip, and retry on
#      a non-fast-forward rejection.
#
# Usage:
#   publish_manifest.sh "<commit message>" <updater argv...>
# where the updater argv contains the literal token @MANIFEST@, replaced with
# the worktree's manifest path on each attempt. The updater is expected to be an
# idempotent `update_manifest.py` invocation (it replaces its own entry in place).
set -euo pipefail

BRANCH="nixos-manifest"
COMMIT_MSG="$1"
shift

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

WORKTREE="$(mktemp -d)"
cleanup() { git worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true; }
trap cleanup EXIT

git worktree add --detach "$WORKTREE" >/dev/null
MANIFEST="$WORKTREE/update-manifest.json"

for attempt in 1 2 3 4 5; do
  git fetch origin "$BRANCH" >/dev/null 2>&1 || true

  if git show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
    git -C "$WORKTREE" checkout -q -B "$BRANCH" "refs/remotes/origin/$BRANCH"
    # Force tree + index to the true tip. A plain checkout after a failed push
    # leaves the stale prior attempt in place (dangling HEAD), which would
    # silently drop the concurrent writer's entry.
    git -C "$WORKTREE" reset -q --hard "refs/remotes/origin/$BRANCH"
  else
    # First ever publish: history-free orphan so the branch never inherits source.
    git -C "$WORKTREE" checkout -q --orphan "$BRANCH"
    git -C "$WORKTREE" rm -rfq --cached . >/dev/null 2>&1 || true
  fi

  # Collapse the working tree to just the manifest; `add -A` below stages the
  # removal of anything the tip still carried.
  find "$WORKTREE" -mindepth 1 -maxdepth 1 \
    ! -name .git ! -name update-manifest.json -exec rm -rf {} +

  cmd=()
  for arg in "$@"; do
    cmd+=( "${arg/@MANIFEST@/$MANIFEST}" )
  done
  "${cmd[@]}"

  git -C "$WORKTREE" add -A
  if git -C "$WORKTREE" diff --staged --quiet; then
    echo "Manifest unchanged"
    exit 0
  fi

  git -C "$WORKTREE" commit -q -m "$COMMIT_MSG"
  if git -C "$WORKTREE" push origin "HEAD:$BRANCH" 2>/dev/null; then
    echo "Manifest published (attempt $attempt)"
    exit 0
  fi

  echo "Push rejected by a concurrent update; retrying ($attempt/5)"
  sleep $((attempt * 2))
done

echo "Failed to publish manifest after 5 attempts" >&2
exit 1
