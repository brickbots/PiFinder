# The btrfs root of the PiFinder SD images (ADR 0039): nixpkgs'
# nixos/lib/make-btrfs-fs.nix plus the PiFinder_data subvolume and zstd
# compression, the same layout the migration makes. make-btrfs-fs.nix itself
# makes no subvolumes. sd-image.nix calls this through
# sdImage.rootFilesystemCreator with the arguments below.
{
  pkgs,
  lib,
  # List of derivations to be included
  storePaths,
  # Whether or not to compress the resulting image with zstd
  compressImage ? false,
  zstd,
  # Shell commands to populate the ./files directory.
  # All files in that directory go to the root of the FS.
  populateImageCommands ? "",
  volumeLabel,
  uuid ? "44444444-4444-4444-8888-888888888888",
  btrfs-progs,
  libfaketime,
  fakeroot,
}:

let
  sdClosureInfo = pkgs.buildPackages.closureInfo { rootPaths = storePaths; };
in
pkgs.stdenv.mkDerivation {
  name = "btrfs-fs.img${lib.optionalString compressImage ".zst"}";

  nativeBuildInputs = [
    btrfs-progs
    libfaketime
    fakeroot
  ]
  ++ lib.optional compressImage zstd;

  buildCommand = ''
    ${if compressImage then "img=temp.img" else "img=$out"}

    set -x
    (
        mkdir -p ./files
        ${populateImageCommands}
    )

    mkdir -p ./rootImage/nix/store

    xargs -I % cp -a --reflink=auto % -t ./rootImage/nix/store/ < ${sdClosureInfo}/store-paths
    (
      GLOBIGNORE=".:.."
      shopt -u dotglob

      # Move, not copy: ./files is scratch, and the full image puts the
      # catalog images (several GB) here.
      for f in ./files/*; do
          mv -t ./rootImage/ "$f"
      done
    )

    # User data lives in its own subvolume (ADR 0039).
    mkdir -p ./rootImage/home/pifinder/PiFinder_data

    cp ${sdClosureInfo}/registration ./rootImage/nix-path-registration

    touch $img
    faketime -f "1970-01-01 00:00:01" fakeroot mkfs.btrfs -L ${volumeLabel} -U ${uuid} \
      -r ./rootImage --subvol rw:home/pifinder/PiFinder_data --compress zstd:1 --shrink $img

    if ! btrfs check $img; then
      echo "--- 'btrfs check' failed for BTRFS image ---"
      return 1
    fi

    if [ ${toString compressImage} ]; then
      echo "Compressing image"
      zstd -v --no-progress ./$img -o $out
    fi
  '';
}
