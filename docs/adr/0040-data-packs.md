# Large data ships as optional data packs: one Nix profile per pack, updated by Attic chunks

**Status:** decided 2026-09-26, not built. The Gaia deep chart pack belongs to the `deepchart` branch and comes later.

PiFinder has large data sets: the catalog images (about 5 GB) and the Gaia deep chart (about 1 GB), and more will come. They do not belong in the system closure: the first boot after the migration would then wait for gigabytes, and each system update would wait for data.

**A pack is a store path.** CI builds each pack from **shards**. A shard is a fixed-output derivation: a folder of files whose store path comes from the hash of its content. The same files always give the same store path. The pack itself is a small derivation with symlinks to its shards. Attic signs everything, and the update manifest lists each pack with its name, size and store path. A shard stays below 256 MiB.

**One profile per pack on the Pi.** For example `/nix/var/nix/profiles/packs/catalog-images`. A profile is a garbage-collection root, so Nix keeps the pack and its shards. The app reads data only through the profile link, so a switch to a new pack version is atomic for the app.

**A root service, `pifinder-packs`, makes the profiles match the selection** in `/var/lib/pifinder/packs.json`. It runs when that file changes, when the network comes up, and after each system update.

- **On:** `nix build <pack> --max-jobs 0`, then `nix-env -p /nix/var/nix/profiles/packs/<name> --set <pack>`.
- **Off:** remove the profile, then garbage-collect.
- **Update:** the same as on, with the new pack path. Shards that did not change keep their store path and download nothing.

The service writes its progress to a status file.

**Transfer by Attic chunks.** A shard that changed downloads as the Attic chunks the Pi does not have:

- The server lists the chunks of the target NAR in order, with their hashes, and serves single chunks.
- The Pi cuts the NARs and files it has into chunks, with the FastCDC version and settings of Attic, and hashes them.
- The Pi downloads only the chunks it does not have and writes the NAR in order. Nix imports it through the local cache and checks the signed NAR hash.

This streams, so the memory use stays small for any size. A compiled helper does the chunking, because Python is too slow for gigabytes on a Pi. Any failure falls back to a normal Nix download.

**Images already on a card.** A migrated card keeps `PiFinder_data/catalog_images` ([ADR 0039](./0039-card-layout-and-migration.md)). For each shard, the Pi arranges the kept files in the shape of the shard and runs `nix-store --add-fixed --recursive sha256`. If the files are the same as in the build, the result is exactly the shard's store path, so Nix downloads nothing for it. A reflink copy on btrfs uses no extra space. Files that differ are still a chunk source.

**Two SD images.**

- **Full:** the packs that are on by default are in the store, with their profiles.
- **Lean:** no packs.

**User interface.** There are no pop-ups in the observing tool, and no web UI for packs for now.

- **Tools > Data packs** is the only place to get or update a pack. It shows the size, the free space and the state: "Get", a percentage, "Installed", or "Needs <size>" when the pack does not fit.
- Nothing downloads until the user presses "Get". A pack that is on by default shows "Get" on a lean card.
- An object without an image shows "No image / Download at: Tools > Data packs", and during the download "Image downloading".
- The catalog image pack and the Gaia pack are optional and on by default. Other optional packs are off by default.

## Considered options

- **Data in the system closure, rejected.** One version for code and data, but the first boot and each update wait for all data, and a failed data download fails the update.
- **One shared data profile for all packs, rejected.** Combining packs into one profile needs a Nix build on the Pi. One profile per pack needs only `nix-env --set`.
- **zstd patches from the differ for data ([ADR 0036](./0036-delta-updates-on-demand-differ.md)), rejected for packs.** A patch needs RAM equal to its window, and the window must cover the whole old NAR. The Pi allows 256 MiB, so a 1 GB NAR downloads in full. 0036 rejected chunks for system paths, because a Nix hash rewrite changes a few bytes in thousands of files. Pack files do not change with each build, so chunks work well for them.
- **Only the per-object CDN download (today's app), rejected as the only way.** It needs internet at the telescope. It stays as the fallback for an object whose pack is not installed.
- **A download prompt at the first internet connection, rejected.** No pop-ups in the observing tool.
- **A title-bar icon during a download, rejected.** The title bar has no free space.

## Consequences

- The app must work with a pack that is missing or older. Each pack has a format version, and the app refuses a format it does not know.
- The chunk transfer needs a server endpoint beside the differ, and a helper that uses the exact FastCDC version, settings and chunk hash of Attic.
- CI must build and push the shards. The catalog images are 5 GB, so CI must build them only when they change.
- The cleanup after a pack update frees only the old shards that no pack uses.
