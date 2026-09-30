# The UI reads shared state from a shared-memory snapshot, with one lock per slot

**Status: accepted.** Design: `ui-performance-plan.md`, step 1.

The shared state (`SharedStateObj`) lives in a `multiprocessing` manager process. Every read through its proxy is a socket round trip. The UI thread made about 14 of these reads per frame. During each wait it releases the GIL, and a busy thread in the UI process (the catalog loader) could keep the GIL for up to the switch interval, 5 ms by default. While catalogs loaded, the UI on a CM4 ran at 2 FPS.

So the manager process also writes the most-read values into one `multiprocessing.shared_memory` block (`PiFinder/state_snapshot.py`):

- The manager process is the only writer. After a `SharedStateObj` setter changes a value, it publishes the value into its slot. The setters and their rules (the timezone lookup, the datetime latch, the power-state check) do not change.
- Each slot holds a version, a length and a pickle, and has its own `multiprocessing.Lock`. The writer holds the lock while it writes. A reader holds it only while it copies the bytes, and decodes after it releases the lock.
- The main loop reads one `StateSnapshot` per frame into `UIModule.snapshot`. A read is a memory copy, with no round trip. An unheld lock is taken with `sem_trywait`, so the reader keeps the GIL.
- `StateSnapshot` has the getter names of `SharedStateObj`, so code that only reads state takes either one.
- A heartbeat slot, written once a second, makes a reader raise `SharedStateLost` when the manager stops, as a proxy call does.

## Considered options

- **One lock per slot (chosen).** The values in different slots have no relation, so there is no lock for the whole block. One value is many fields (a solution holds RA, Dec, roll and times), so a reader must never copy a half-written slot. A lock makes that impossible by construction. A test with the locks replaced by no-ops found 127 half-written values and 11,271 decode errors in 1.5 s; with the locks it finds none.
- **A sequence counter (seqlock), rejected.** It is correct only when the writes to the counter and to the data reach memory in order. The ARM CPU in the CM4 can change that order, and Python cannot add the memory barriers that C code uses.
- **Fewer proxy reads and a 1 ms switch interval only (PR #111), kept but not enough.** It halves the reads and shortens each wait, but every read is still a round trip.
- **Free-threaded Python (no GIL), rejected for now.** Python turns the GIL back on for a C extension without free-thread support, some of our extensions may not have it, the Nix build would lose the binary cache, and the IPC round trips would stay.

## Consequences

- In a headless run, the UI main thread makes no manager read in a normal frame. It still sends the screen image when the image changes.
- The snapshot changes only between frames. A screen that waits in a loop for a new value (the SQM calibration and sweep screens) keeps the proxy.
- Values in a snapshot are shared by all its users and must be treated as read-only. State changes go through the setters.
- Only the UI reads the snapshot. The web server, pos_server and the worker processes still use the proxy and can move to the snapshot later.
- A value larger than its slot is not written, and the writer logs an error. The slot sizes allow a solution with many matched stars (16 KB).
