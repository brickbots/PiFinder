{ pkgs, lib ? pkgs.lib, pyproject-nix, uv2nix, pyproject-build-systems }:
let
  python = pkgs.python313;

  # The uv workspace lives at the repo root (python/pyproject.toml + uv.lock).
  workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ../../python; };

  # Prefer prebuilt wheels; fall back to sdist where no wheel exists.
  overlay = workspace.mkPyprojectOverlay { sourcePreference = "wheel"; };

  # Native/C-extension packages that can't build from PyPI metadata alone.
  # These mirror the patches the old hand-written python-packages.nix carried.
  pyprojectOverrides = final: prev: {
    python-libinput = prev.python-libinput.overrideAttrs (old: {
      nativeBuildInputs =
        (old.nativeBuildInputs or [])
        ++ [ pkgs.pkg-config ]
        ++ final.resolveBuildSystem { setuptools = []; };
      buildInputs = (old.buildInputs or []) ++ [ pkgs.libinput pkgs.systemd ];
      postPatch = (old.postPatch or "") + ''
        substituteInPlace setup.py \
          --replace-fail 'from imp import load_source' 'import importlib.util, types
def load_source(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod'
        substituteInPlace libinput/__init__.py \
          --replace-fail "CDLL('libudev.so.1')" "CDLL('${lib.getLib pkgs.systemd}/lib/libudev.so.1')" \
          --replace-fail "CDLL('libinput.so.10')" "CDLL('${lib.getLib pkgs.libinput}/lib/libinput.so.10')"
      '';
    });

    python-prctl = prev.python-prctl.overrideAttrs (old: {
      nativeBuildInputs =
        (old.nativeBuildInputs or [])
        ++ final.resolveBuildSystem { setuptools = []; };
      buildInputs = (old.buildInputs or []) ++ [ pkgs.libcap ];
    });

    python-pam = prev.python-pam.overrideAttrs (old: {
      postPatch = (old.postPatch or "") + ''
        substituteInPlace src/pam/__internals.py \
          --replace-fail 'find_library("pam")' '"${pkgs.pam}/lib/libpam.so"' \
          --replace-fail 'find_library("pam_misc")' '"${pkgs.pam}/lib/libpam_misc.so"'
      '';
    });

    # dbus-python and PyGObject build from sdist with meson-python; meson needs
    # the C libraries + pkg-config on the build inputs.
    dbus-python = prev.dbus-python.overrideAttrs (old: {
      nativeBuildInputs = (old.nativeBuildInputs or []) ++ [ pkgs.pkg-config ];
      buildInputs = (old.buildInputs or []) ++ [ pkgs.dbus pkgs.glib ];
    });

    pygobject = prev.pygobject.overrideAttrs (old: {
      nativeBuildInputs = (old.nativeBuildInputs or []) ++ [ pkgs.pkg-config ];
      buildInputs =
        (old.buildInputs or [])
        ++ [ pkgs.glib pkgs.gobject-introspection pkgs.cairo ];
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
  # Runtime env: [project.dependencies] only.
  pifinderEnv = pythonSet.mkVirtualEnv "pifinder-env" workspace.deps.default;
  # Dev env: adds the [dependency-groups].dev set (pytest, mypy, selenium…).
  devEnv = pythonSet.mkVirtualEnv "pifinder-dev-env" workspace.deps.all;
}
