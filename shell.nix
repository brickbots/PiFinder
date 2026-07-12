# Classic-nix entry point for the devShell, used by direnv (.envrc: `use nix`).
#
# `use flake` would copy the entire working tree (~1.3 GB: astro_data, images,
# docs, python/.venv, …) into /nix/store on every flake change, because nix
# hashes the whole flake source. The devShell only needs the flake files,
# nixos/, and python/ (sans .venv) — so build a filtered copy (~25 MB) and
# evaluate the flake through flake-compat with that as its source.
#
# CI and remote builds keep evaluating the flake directly via github: refs;
# they fetch this file with the repository but do not evaluate it.
let
  flake-compat = builtins.fetchTarball {
    url = "https://github.com/edolstra/flake-compat/archive/5edf11c44bc78a0d334f6334cdaf7d60d732daab.tar.gz";
    sha256 = "0yqfa6rx8md81bcn4szfp0hjq2f3h9i8zjzhqqyfqdkrj5559nmw";
  };

  # Only what the devShell evaluation actually reads.
  wanted = [ "flake.nix" "flake.lock" "nixos" "python" ];

  src = builtins.path {
    path = ./.;
    name = "pifinder-devshell-src";
    filter = path: type:
      let
        rel = builtins.substring (builtins.stringLength (toString ./. + "/"))
          (builtins.stringLength path) (toString path);
        top = builtins.head (builtins.split "/" rel);
      in
      builtins.elem top wanted && rel != "python/.venv";
  };

  flake = import flake-compat { inherit src; };
in
flake.defaultNix.devShells.${builtins.currentSystem}.default
