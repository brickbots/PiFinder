# Updates transfer byte-level NAR deltas, computed on demand beside the cache

A NixOS store path is downloaded whole, and its name contains the hash of its
inputs, so a one-line source edit renames — and re-downloads — hundreds of
paths whose bytes barely changed. Measured on real CI build pairs, ~255 MiB of
"changed" store paths differ by ~1.5 MiB of actual content (0.6%). Devices
update over phone hotspots in the field; bytes on the wire should track the
real content difference between any two versions.

The upgrade therefore prefetches patches before nix downloads anything
(`delta_updates.py`, called from `nixos_upgrade.py`): for each missing path it
names the newest same-stem paths it already holds — across all retained
generations — and a server (`pifinder-differ`, running beside the Attic cache)
answers with a `zstd --patch-from` patch between the two paths' NARs. The
device reconstructs the target NAR from `nix-store --dump` of its base
(canonical on both ends), verifies sha256 **before** `nix-store --import`
(import does not check the NAR against the path name), and assembles the
import framing locally from the response's references and deriver. Pairs are
computed once, on first request, and cached forever; the server pre-warms
predictable pairs in the background. Requests are budgeted per update: the
device opens a session naming its target toplevel and the server sizes the
request budget from that closure.

## Considered Options

- **Pre-compute all pairs in CI, serve static files.** Cannot cover arbitrary
  version pairs (n² at hundreds of releases) and couples every release to a
  patch-build step. Rejected as the primary mechanism; it survives as the
  server's self-warming, which needs no CI involvement at all.
- **Styx (lazy chunk substitution via EROFS/fscache).** Purpose-built, but
  experimental, kernel-resident in the boot path, and lazy fetch is wrong for
  a telescope that must work offline: it would need a "pull everything"
  pass that discards its main advantage and keeps its risk.
- **Content-defined chunking (casync/desync/bita).** Base-agnostic and
  CDN-friendly, but has a chunk-sized floor (~64 KiB): a Nix hash rewrite
  touches a few bytes in thousands of files, dirtying nearly every chunk.
  Weakest exactly on the dominant case. (The differ still uses Attic's
  FastCDC chunk lists — as a free similarity index for ranking candidate
  bases, not as the transfer unit.)
- **Content-addressed derivations.** Removes rebuild fan-out only for
  bit-identical rebuilds; helps nothing on a real code change. Complementary,
  not a transport.
- **Per-IP rate limiting on the server.** Fails both directions: devices
  sharing a hotspot NAT starve each other, attackers rotate addresses.
  Replaced by per-update session budgets derived from the target closure's
  size in the cache database — inflatable by nobody, fair behind NAT.

## Consequences

- **Off by default.** `pifinder.deltaUrl = ""` disables the entire path; every
  failure (server down, bad patch, disk full, corrupt base, exhausted budget)
  falls back to a normal binary-cache download, per path. The delta layer can
  only reduce downloads, never block an upgrade.
- The sha256-before-import check is load-bearing. A patch applied without it
  can register a corrupt path as valid. Never import an unverified stream.
- Patching needs base NAR + patch + reconstructed NAR on disk at once
  (~2× NAR size) and `2^window_log` bytes of decode memory. The device caps
  `window_log` at 28 (256 MiB); paths larger than the cap fall back to full
  download.
- The server is a new operational component (loopback service behind a Caddy
  vhost, `deltas.pifinder.eu`). It reads Attic's SQLite DB and NAR bytes, so
  it inherits Attic's availability — and Attic's retention holes: a path GC'd
  from the cache simply cannot be patched, which degrades per path by design.
- Delta bases are whatever old generations the device retains; GC policy on
  the device is therefore part of the bandwidth story, not just the rollback
  story.
