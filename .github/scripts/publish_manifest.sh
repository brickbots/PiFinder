#!/usr/bin/env bash
# Update update-manifest.json on the metadata-only `nixos-manifest` branch.
#
# The branch holds only that one JSON file; it carries no source tree. The job
# here is just: read the current manifest, let the updater rewrite its entry,
# and push. Concurrency-safe: a git ref update is compare-and-swap, so if a
# concurrent writer lands first our push is rejected, and we re-fetch the new
# tip, re-apply this run's entry onto it, and retry.
#
# Usage:
#   publish_manifest.sh "<commit message>" <updater argv...>
# The updater argv contains the literal token @MANIFEST@, replaced with the
# manifest path on each attempt. It must be idempotent (replaces its own entry).
set -euo pipefail

BRANCH="nixos-manifest"
COMMIT_MSG="$1"
shift

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

WORKTREE="$(mktemp -d)"
trap 'git worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true' EXIT
git worktree add --detach "$WORKTREE" >/dev/null
MANIFEST="$WORKTREE/update-manifest.json"

for attempt in 1 2 3 4 5; do
  git fetch origin "$BRANCH" >/dev/null 2>&1 || true

  if git show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
    # reset --hard so a retry after a rejected push starts from the true tip,
    # not the stale entry from the previous attempt (which would otherwise
    # silently drop the concurrent writer's change).
    git -C "$WORKTREE" checkout -q -B "$BRANCH" "refs/remotes/origin/$BRANCH"
    git -C "$WORKTREE" reset -q --hard "refs/remotes/origin/$BRANCH"
  else
    # Branch does not exist yet: start it empty.
    git -C "$WORKTREE" checkout -q --orphan "$BRANCH"
    git -C "$WORKTREE" rm -rfq --cached . >/dev/null 2>&1 || true
  fi

  cmd=()
  for arg in "$@"; do
    cmd+=( "${arg/@MANIFEST@/$MANIFEST}" )
  done
  "${cmd[@]}"

  git -C "$WORKTREE" add update-manifest.json
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
