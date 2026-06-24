# NixOS — architecture notes

Companion to [`nixos/CONTEXT.md`](./nixos/CONTEXT.md): how the pieces named there actually move. Sections are added as they're worked through; today it covers the on-device download.

## Installing a version (download, availability, progress)

Installing any version works the same way whether it's a channel pick, a rollback, or the first-boot download during the move to NixOS: the device **downloads** the files that make up that version from the cache and switches to them. It never rebuilds anything — if a file is missing from the cache, the install stops rather than compiling it.

### One up-front query, two jobs

When a version is chosen, the device makes a single request to the cache for that version's complete set of files and each file's download size. From the answer it gets:

- **The download size, up front.** Drop the files already on the device, add up the sizes of the rest — a fixed total in megabytes, known before the download starts.
- **Whether the version is still there.** If the cache can't return the full set, the version has been removed: stop immediately with "no longer available" instead of failing partway through. Only **unstable** versions can reach this state; **stable** and **beta** are kept forever (see [`nixos/CONTEXT.md`](./nixos/CONTEXT.md) and [ADR 0002](./nixos/adr/0002-update-channels-and-rollback.md)). The check happens at the moment a version is picked, so browsing the list costs nothing.

### Progress

The bar is **size-based**: megabytes downloaded out of the up-front total, advancing each time a file finishes (its known size is added to the running total). Because the total is fixed from the start, the bar is honest from the first moment.

This replaces the earlier behaviour, which counted files against a total that itself grew as the download proceeded — so early percentages were meaningless, and even a correct count would misreport progress because file sizes vary by orders of magnitude. The first-boot download already fixed its total up front but still counted files; it moves to the same size-based approach so both downloads behave identically.
