{ config, lib, pkgs, pyproject-nix, uv2nix, pyproject-build-systems, ... }:
let
  env = (import ./pkgs/uv-python.nix {
    inherit pkgs lib pyproject-nix uv2nix pyproject-build-systems;
  }).pifinderEnv;
in {
  # libcamera overlay — enable Python bindings for picamera2
  nixpkgs.overlays = [(final: prev: {
    libcamera = prev.libcamera.overrideAttrs (old: {
      mesonFlags = (old.mesonFlags or []) ++ [
        "-Dpycamera=enabled"
      ];
      buildInputs = (old.buildInputs or []) ++ [
        final.python313
        final.python313.pkgs.pybind11
      ];
    });
  })];

  environment.systemPackages = [
    env
    pkgs.gobject-introspection
    pkgs.networkmanager
    pkgs.libcamera
    pkgs.gpsd
  ];

  # Ensure GI_TYPELIB_PATH includes NetworkManager typelib
  environment.sessionVariables.GI_TYPELIB_PATH = lib.makeSearchPath "lib/girepository-1.0" [
    pkgs.networkmanager
    pkgs.glib
  ];

  # Add libcamera Python bindings to PYTHONPATH (for picamera2)
  environment.sessionVariables.PYTHONPATH = "${pkgs.libcamera}/lib/python3.13/site-packages";

  # Export the Python environment for use by services.nix
  _module.args.pifinderPythonEnv = env;
}
