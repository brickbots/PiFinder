{ pkgs, lib ? pkgs.lib, pyproject-nix, uv2nix, pyproject-build-systems }:
let
  python = pkgs.python313;

  workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ../../python; };

  overlay = workspace.mkPyprojectOverlay { sourcePreference = "wheel"; };

  # Only the overrides that are needed on macOS — Linux-only packages
  # (spidev, rpi-gpio, picamera2, dbus-python, pygobject, python-libinput,
  # python-prctl, python-pam, evdev, adafruit-blinka, pidng, videodev2) are
  # gated behind sys_platform == 'linux' in pyproject.toml so they are never
  # resolved for this platform and need no override here.
  pyprojectOverrides = final: prev: {
    # cedar-solve (the tetra3 plate-solver) is installed from git source and
    # uses setup.py but doesn't declare setuptools as a build dependency.
    cedar-solve = prev.cedar-solve.overrideAttrs (old: {
      nativeBuildInputs =
        (old.nativeBuildInputs or [])
        ++ final.resolveBuildSystem { setuptools = []; };
    });

    timezonefinder = prev.timezonefinder.overrideAttrs (old: {
      nativeBuildInputs =
        (old.nativeBuildInputs or [])
        ++ final.resolveBuildSystem { setuptools = []; };
    });

    sh = prev.sh.overrideAttrs (old: {
      nativeBuildInputs =
        (old.nativeBuildInputs or [])
        ++ final.resolveBuildSystem { setuptools = []; };
    });
  };

  pythonSet =
    (pkgs.callPackage pyproject-nix.build.packages { inherit python; }).overrideScope
      (lib.composeManyExtensions [
        pyproject-build-systems.overlays.default
        overlay
        pyprojectOverrides
      ]);
in {
  inherit pythonSet;
  pifinderEnv = pythonSet.mkVirtualEnv "pifinder-env" workspace.deps.default;
  devEnv = pythonSet.mkVirtualEnv "pifinder-dev-env" workspace.deps.all;
}
