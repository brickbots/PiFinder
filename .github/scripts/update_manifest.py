#!/usr/bin/env python3
"""Update the generated PiFinder software update manifest."""

import argparse
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


STORE_PATH_RE = re.compile(r"^/nix/store/[a-z0-9]+-[A-Za-z0-9._+=?,-]+$")

# The binary caches devices resolve upgrades from. A build is only advertised
# as available once one of these actually serves its narinfo — see set_available.
DEV_CACHE = "https://cache.pifinder.eu/pifinder"
RELEASE_CACHE = "https://cache.pifinder.eu/pifinder-release"
DEFAULT_CACHES = (DEV_CACHE, RELEASE_CACHE)
EMPTY_MANIFEST = {
    "schema": 1,
    "generated_at": None,
    "channels": {
        "stable": [],
        "beta": [],
        "unstable": [],
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_manifest(path: Path) -> dict:
    if not path.exists():
        return json.loads(json.dumps(EMPTY_MANIFEST))
    with path.open() as f:
        data = json.load(f)
    if data.get("schema") != 1:
        raise SystemExit(f"unsupported manifest schema in {path}")
    channels = data.setdefault("channels", {})
    for name in ("stable", "beta", "unstable"):
        channels.setdefault(name, [])
    return data


def save_manifest(path: Path, manifest: dict) -> None:
    manifest["generated_at"] = now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")


def valid_store_path(value: str | None) -> bool:
    return isinstance(value, str) and STORE_PATH_RE.fullmatch(value) is not None


def _narinfo_url(store_path: str, cache: str) -> str:
    digest = Path(store_path).name.split("-", 1)[0]
    return f"{cache.rstrip('/')}/{digest}.narinfo"


def cache_serves(store_path: str, caches, timeout: int = 15) -> bool | None:
    """Whether the closure is actually downloadable from a cache right now.

    Returns True if any cache serves the narinfo (200); False only if every
    cache answered and none had it (a real 404 everywhere); None if a cache
    could not be reached, so presence is unknown. Publishing treats anything
    other than True as "do not advertise", so a failed push or a down cache can
    never advertise a build the device cannot fetch.
    """
    saw_404 = False
    for cache in caches:
        url = _narinfo_url(store_path, cache)
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                if resp.status == 200:
                    return True
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                saw_404 = True
            else:
                return None
        except (urllib.error.URLError, OSError, TimeoutError):
            return None
    return False if saw_404 else None


def set_available(entry: dict, caches=DEFAULT_CACHES, verify: bool = True) -> dict:
    store_path = entry.get("store_path")
    if not valid_store_path(store_path):
        entry["store_path"] = None
        entry["available"] = False
        entry.setdefault("reason", "no build")
        return entry

    if verify:
        present = cache_serves(store_path, caches)
        if present is not True:
            entry["available"] = False
            entry["reason"] = "not in cache" if present is False else "cache unreachable"
            return entry

    entry["available"] = True
    entry.pop("reason", None)
    return entry


def replace_entry(entries: list[dict], predicate, entry: dict) -> list[dict]:
    # Newest first: consumers (release channels in the update UI, and the
    # migration target lookup) take the head of the list as the current entry.
    # The unstable channel is re-sorted after this, so prepending is neutral
    # there.
    return [entry] + [item for item in entries if not predicate(item)]


def sort_unstable(entries: list[dict]) -> list[dict]:
    def key(item: dict) -> tuple[int, int, str]:
        if item.get("kind") == "trunk":
            return (0, 0, item.get("source_ref", ""))
        if item.get("kind") == "pr":
            return (1, -int(item.get("number") or 0), item.get("label", ""))
        return (2, 0, item.get("label", ""))

    return sorted(entries, key=key)


def resolve_verify(args: argparse.Namespace) -> tuple[tuple[str, ...], bool]:
    caches = tuple(args.verify_cache) if args.verify_cache else DEFAULT_CACHES
    return caches, not args.skip_cache_check


def update_build(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.manifest)
    channels = manifest["channels"]
    store_path = args.store_path or None
    short_sha = (args.head_sha or args.sha)[:7]
    caches, verify = resolve_verify(args)

    if args.pr_number:
        number = int(args.pr_number)
        entry = {
            "kind": "pr",
            "number": number,
            "label": f"PR#{number}-{short_sha}",
            "title": args.pr_title or f"PR #{number}",
            "notes": args.pr_body or None,
            "source_repo": args.head_repo,
            "source_ref": args.head_ref,
            "source_sha": args.head_sha,
            "version": args.version or f"PR#{number}-{short_sha}",
            "store_path": store_path,
            "built_at": now_iso(),
        }
        set_available(entry, caches, verify)
        channels["unstable"] = replace_entry(
            channels["unstable"],
            lambda item: item.get("kind") == "pr"
            and int(item.get("number") or 0) == number,
            entry,
        )
    else:
        entry = {
            "kind": "trunk",
            "label": args.version or f"{args.ref_name}-{short_sha}",
            "title": f"{args.ref_name} branch",
            "notes": None,
            "source_repo": args.repository,
            "source_ref": args.ref_name,
            "source_sha": args.sha,
            "version": args.version or f"{args.ref_name}-{short_sha}",
            "store_path": store_path,
            "built_at": now_iso(),
        }
        set_available(entry, caches, verify)
        channels["unstable"] = replace_entry(
            channels["unstable"],
            lambda item: item.get("kind") == "trunk"
            and item.get("source_repo") == args.repository
            and item.get("source_ref") == args.ref_name,
            entry,
        )

    channels["unstable"] = sort_unstable(channels["unstable"])
    save_manifest(args.manifest, manifest)


def update_release(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.manifest)
    caches, verify = resolve_verify(args)
    channel = "beta" if args.release_type == "beta" else "stable"
    entry = {
        "kind": "release",
        "label": args.tag,
        "title": args.title or f"PiFinder {args.tag}",
        "notes": args.notes or None,
        "source_repo": args.repository,
        "source_ref": args.tag,
        "source_sha": args.sha,
        "version": args.version,
        "store_path": args.store_path or None,
        "migration_url": args.migration_url or None,
        "migration_sha256_url": args.migration_sha256_url or None,
        "built_at": now_iso(),
    }
    set_available(entry, caches, verify)
    manifest["channels"][channel] = replace_entry(
        manifest["channels"][channel],
        lambda item: item.get("kind") == "release" and item.get("label") == args.tag,
        entry,
    )
    save_manifest(args.manifest, manifest)


def add_cache_args(sub: argparse.ArgumentParser) -> None:
    # A build is advertised as available only if one of these caches actually
    # serves its narinfo. Repeatable; defaults to the dev + release caches.
    sub.add_argument("--verify-cache", action="append", metavar="URL")
    sub.add_argument(
        "--skip-cache-check",
        action="store_true",
        help="advertise on store-path syntax alone (tests / offline only)",
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build")
    build.add_argument("--manifest", type=Path, required=True)
    build.add_argument("--repository", required=True)
    build.add_argument("--ref-name", required=True)
    build.add_argument("--sha", required=True)
    build.add_argument("--store-path", required=True)
    build.add_argument("--version", required=True)
    build.add_argument("--pr-number")
    build.add_argument("--pr-title")
    build.add_argument("--pr-body")
    build.add_argument("--head-repo")
    build.add_argument("--head-ref")
    build.add_argument("--head-sha")
    add_cache_args(build)
    build.set_defaults(func=update_build)

    release = sub.add_parser("release")
    release.add_argument("--manifest", type=Path, required=True)
    release.add_argument("--repository", required=True)
    release.add_argument("--sha", required=True)
    release.add_argument("--tag", required=True)
    release.add_argument("--version", required=True)
    release.add_argument("--release-type", choices=("stable", "beta"), required=True)
    release.add_argument("--store-path", required=True)
    release.add_argument("--migration-url")
    release.add_argument("--migration-sha256-url")
    release.add_argument("--title")
    release.add_argument("--notes")
    add_cache_args(release)
    release.set_defaults(func=update_release)

    return root


def main() -> None:
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
