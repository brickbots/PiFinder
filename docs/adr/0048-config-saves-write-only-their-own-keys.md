# Config saves write only their own keys

`Config.set_option` (and `reset_filters`) re-read `config.json`, change only
the keys being saved, and replace the file atomically under an exclusive lock.
A process no longer writes back its whole start-up copy of the settings.

## Context

Every PiFinder process — UI, camera, web server, integrator — builds its own
`Config` when it starts. `set_option` used to call `dump_config()`, which wrote
that process's entire in-memory dict to disk. Whatever any other process had
saved since that process started was silently reverted.

Found while verifying per-telescope alignment
([ADR 0047](0047-alignment-point-belongs-to-the-telescope.md)): leaving
Align (Day) restores a manual exposure, the camera process saves `camera_exp`
from its boot-time copy, and the alignment the UI saved a moment before is
gone from disk. The running PiFinder keeps the right value in memory, so the
loss only shows after a restart — unless a later save from the UI happens to
re-persist it. Picking a manual value in the Camera Exp menu does the same.
The global `target_pixel` was lost the same way before ADR 0047.

The integrator's lens self-heal had already met this and worked around it
locally by calling `load_config()` before each write.

## Decision

1. **A save merges.** `Config._persist(changes, remove=...)` reads the file,
   applies only the given keys (and removals, for `reset_filters`), and
   writes the result. `dump_config()` is gone; nothing else wrote the file
   from a `Config`.
2. **Under a lock.** The read-modify-write holds `fcntl.flock` on
   `.config.json.lock` in the data directory, so two processes saving at the
   same moment cannot drop each other's key.
3. **Atomically.** The new contents go to a temporary file in the same
   directory, take the old file's mode, and `os.replace` it, so a process
   loading the config never reads half a file.
4. **A missing or unreadable file** is rebuilt from what the saving process
   knows — the same thing the old whole-dict write did, and the best copy
   available.

## Considered options

- **Reload before every write, as the integrator does.** Fixes each call site
  that remembers to do it, and every new process or call site starts out
  wrong. It also re-runs the whole `load_config` (equipment, locations) for
  one key.
- **Have the camera process stop saving the exposure.** Removes the trigger
  that was found, not the defect: any process that saves anything can do it.
- **One owner process for config writes, reached over a queue.** The right
  shape for a larger redesign, but a far bigger change than the defect needs.

## Consequences

- **A process's in-memory view is still its own.** Saving does not refresh
  the other keys in memory; `load_config()` (as on `reload_config`) is still
  how a process picks up other processes' changes.
- **The unit of a save is one top-level key.** `equipment` and `locations`
  are single keys, so two processes saving different telescopes still race at
  that level. Only the UI and the web server save equipment, and the web
  server builds a fresh `Config` per request, so this does not arise today.
- **`fcntl` ties `config.py` to POSIX.** PiFinder runs on Linux and is
  developed on Linux and macOS.
- **The integrator's reload stays.** It no longer protects the write, but it
  still keeps that process's view of the config current.
