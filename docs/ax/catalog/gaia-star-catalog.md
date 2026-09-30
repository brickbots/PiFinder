# Gaia star catalog (deep charts)

The deep chart draws stars from a Gaia DR3 catalog of 157,564,358 stars down
to magnitude 17. This document describes the files, how the reader finds a
star, and how the catalog gets to a PiFinder.

- Reader: `python/PiFinder/object_images/star_catalog.py`
- Chart: `python/PiFinder/object_images/gaia_chart.py`
- Nix package: `nixos/pkgs/gaia-stars.nix`
- Files: `https://files.miker.be/public/pifinder/gaia_stars_v3/`

## 1. Layout on the device

`~/PiFinder_data/gaia_stars` is a link to the Nix package. The package is a
directory of links:

```
gaia_stars/
├── metadata.json
├── mag_00_06/ index.bin tiles.bin
├── mag_06_09/ index.bin tiles.bin
├── mag_09_12/ index.bin tiles.bin
├── mag_12_14/ index.bin tiles.bin
├── mag_14_16/ index.bin tiles.bin
└── mag_16_17/ index.bin tiles.bin
```

Each `mag_XX_YY` directory holds the stars with a magnitude from XX up to,
but not including, YY. The reader opens both files of a band with mmap. It
reads the bright bands first, so the chart shows bright stars before the
faint bands have loaded.

## 2. The sky grid

The sky is cut into HEALPix pixels, nside 512, nested scheme. That gives
3,145,728 pixels of about 6.9′ × 6.9′. A **tile** is the set of stars of one
band in one pixel. A tile is stored only when it has at least one star.

For a chart, `healpy.query_disc` gives the pixels that cover the field of
view. The reader then reads those tiles from each band.

## 3. metadata.json

```json
{
  "format": "columnar",
  "catalog_version": "3.0",
  "source": "Gaia DR3",
  "catalog_epoch": "J2025.90",
  "proper_motion_applied": true,
  "nside": 512,
  "mag_limit": 17.0,
  "star_count": 157564358,
  "mag_bands": [
    {"min": 16, "max": 17, "tiles": 3084452, "stars": 79756083,
     "mag_bits": 4, "mag_base": 160},
    ...
  ]
}
```

The reader accepts only `format` `columnar` with `catalog_version` 3.x. It
refuses any other catalog and shows no deep chart. `mag_bits` and `mag_base`
tell how the band stores magnitudes (section 5).

Proper motion is applied when the catalog is built, for epoch J2025.90. The
reader does not change the positions.

## 4. index.bin: where a tile is

`index.bin` gives, for a HEALPix pixel, the offset and the size of its tile
in `tiles.bin`. It stores one star count for every pixel of the sky, so its
size does not depend on the number of stars.

```
header       version u32 = 4, num_pixels u32, stride u32 = 256,
             num_overflow u32
counts       u8 × num_pixels        stars in the pixel; 255 = see overflow
checkpoints  u64 × ceil(num_pixels / stride)
                                    tiles.bin offset of pixel k × stride
overflow     num_overflow × [pixel u32, count u32], sorted by pixel
```

All numbers are little-endian. `tiles.bin` holds the tiles in pixel order,
back to back, and a pixel with no stars has no tile. To find pixel `p`:

1. If `counts[p]` is 0, the tile does not exist.
2. Take the checkpoint of `p // stride`.
3. Add the byte sizes of the tiles from `(p // stride) × stride` up to `p`
   (at most 255 tiles). A size comes from the star count (section 5).
4. The tile size comes from the star count of `p`.

A count of 255 or more is in the overflow list. Only the dense bands have
such tiles: 6 in mag 12–14, 8,463 in mag 14–16 and 24,530 in mag 16–17.

The counts and the checkpoints stay on the mmap. Only the overflow list is
copied into RAM (about 0.3 MB for all bands).

## 5. tiles.bin: the stars of a tile

A tile has no header. Its pixel comes from the index, and its star count
comes from its size. The stars are stored in three columns:

```
ra_offset  u8 × n
dec_offset u8 × n
magnitude  u8 × n              (mag_bits 8)
           u8 × (n + 1) // 2   (mag_bits 4)
```

So a tile is `3n` bytes, or `2n + (n + 1) // 2` bytes with 4-bit
magnitudes. The reader gets `n` back with `size // 3` or `(2 × size) // 5`.

**Position.** Each offset is a byte from 0 to 255 that spans ±0.75 of the
pixel size (about 2.4″ per step):

```
max_offset = 0.75 × pixel_size
dec = pixel_dec + (dec_offset / 127.5 − 1) × max_offset
ra  = pixel_ra  + (ra_offset  / 127.5 − 1) × max_offset / cos(dec)
```

The pixel centre comes from `healpy.pix2ang(512, pixel, lonlat=True)`.

**Magnitude.** The value is in tenths of a magnitude.

- `mag_bits` 8: one byte per star. The magnitude is `byte / 10`.
- `mag_bits` 4: one nibble per star, for a band that spans at most 16
  tenths. Star `2k` is in the low nibble of byte `k`, and star `2k + 1` is in
  the high nibble. The magnitude is `(mag_base + nibble) / 10`.

Only mag 16–17 uses 4 bits. That band has 10 values, 16.0 to 16.9. The other
bands span 20 or more tenths.

## 6. Sizes

| Band | Stars | Tiles | tiles.bin | index.bin | Download |
|---|---|---|---|---|---|
| mag 0–6 | 6,518 | 6,465 | 0.02 MB | 3.2 MB | 0.04 MB |
| mag 6–9 | 168,967 | 161,760 | 0.5 MB | 3.2 MB | 0.6 MB |
| mag 9–12 | 2,886,832 | 1,605,587 | 8.7 MB | 3.2 MB | 8.6 MB |
| mag 12–14 | 13,653,823 | 2,686,854 | 41.0 MB | 3.2 MB | 38.3 MB |
| mag 14–16 | 61,092,135 | 3,096,994 | 183.3 MB | 3.3 MB | 164.1 MB |
| mag 16–17 | 79,756,083 | 3,084,452 | 200.2 MB | 3.4 MB | 195.4 MB |
| **Total** | 157,564,358 | 10,642,112 | 433.6 MB | 19.7 MB | 407.1 MB |

"Download" is the size of the band's `tar.zst`. The binary cache also sends
the store paths compressed with zstd. On the device, the btrfs root uses
`compress=zstd:1`.

## 7. How the catalog gets to a PiFinder

`nixos/pkgs/gaia-stars.nix` makes one **shard** per band. A shard is a
fixed-output derivation: it fetches `mag_XX_YY.tar.zst` from
files.miker.be and unpacks it. Its store path depends only on its name and
its hash:

- A nixpkgs update does not change a shard, so a device does not download
  the catalog again.
- A band whose files do not change keeps its store path and downloads
  nothing.
- Each shard is below 256 MiB (the largest is 204 MB). The delta updater
  can therefore patch a changed band. It refuses a path above 256 MiB,
  because the patch window must hold the whole old path in RAM.

`metadata.json` is a separate fixed-output fetch. The package itself is a
`linkFarm` of links to the shards and the metadata. `nixos/services.nix`
links it to `~/PiFinder_data/gaia_stars`.

The builder fetches and unpacks. A PiFinder never builds the catalog. It
substitutes the finished paths from the binary cache.

## 8. How to publish a new catalog version

The files on files.miker.be are the source of the catalog. The script that
built the 2.1 catalog from the Gaia archive is not in this repository.

1. Write the new files in a directory with the layout of section 1.
2. Check them: star count, tile ids and the decoded stars against the
   previous version.
3. Make one reproducible tarball per band, with the band directory at the
   top:

   ```bash
   tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
       -cf - mag_16_17 | zstd -19 -T0 -o mag_16_17.tar.zst
   ```

4. Upload the tarballs and `metadata.json` to a new folder,
   `/srv/copyparty/public/pifinder/gaia_stars_vN/` on proxnix. Never change
   the files of a published folder: a fixed-output hash that no longer
   matches breaks each build that needs the path.
5. In `gaia-stars.nix`, set `version`, `baseUrl` and the hashes. The hash of
   a band is `nix hash path mag_XX_YY` of the unpacked directory. The hash of
   the metadata is `nix hash file metadata.json`.
6. If the format changes, change the reader and `CATALOG_MAJOR_VERSION` in
   `star_catalog.py` in the same change.

A shard is fixed-output, so Nix does not fetch it again when only its URL
changes. Always change the hash when the content changes.
