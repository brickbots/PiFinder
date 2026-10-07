{ config, lib, pkgs, pyproject-nix, uv2nix, pyproject-build-systems, ... }:
let
  env = (import ./pkgs/uv-python.nix {
    inherit pkgs lib pyproject-nix uv2nix pyproject-build-systems;
  }).pifinderEnv;
in {
  # libcamera overlay — enable Python bindings for picamera2
  nixpkgs.overlays = [(final: prev: {
    libcamera = prev.libcamera.overrideAttrs (old: {
      # v0.7.2 binds Camera with pybind11's smart holder (upstream cb5fcd20).
      # With v0.7.0 and pybind11 3.0.4 (NixOS 26.05), CameraManager.cameras
      # fails with "Unable to convert std::shared_ptr<T> to Python", so
      # picamera2 finds no camera. Drop this when nixpkgs has >= 0.7.2.
      version = "0.7.2";
      src = final.fetchgit {
        url = "https://git.libcamera.org/libcamera/libcamera.git";
        rev = "v0.7.2";
        hash = "sha256-vhFkeT1j2KKm+CVvGrtH5BEYJSEdaX7N7DRdA0a9EWk=";
      };
      patches = (old.patches or []) ++ [
        ./patches/libcamera-imx290-optical-black.patch
      ];
      # 0.7.2 adds optional features the 0.7.0 recipe does not know, and the
      # recipe turns every auto feature on. Off: the cam tool outputs and the
      # GPU software ISP (the Pi uses its hardware ISP), and libdw backtraces.
      # The nixpkgs master recipe for 0.7.2 turns off the same cam outputs
      # and libdw.
      mesonFlags = (old.mesonFlags or []) ++ [
        "-Dpycamera=enabled"
        "-Dcam-jpeg=disabled"
        "-Dcam-output-sdl2=disabled"
        "-Dapps-output-dng=disabled"
        "-Dsoftisp-gpu=disabled"
        "-Dlibdw=disabled"
      ];
      buildInputs = (old.buildInputs or []) ++ [
        final.python313
        final.python313.pkgs.pybind11
        final.libyuv
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
