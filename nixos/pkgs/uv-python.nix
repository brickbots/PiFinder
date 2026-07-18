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

    # Installed from a prebuilt wheel (no source at patchPhase), so patch the
    # installed module in $out: ctypes find_library("pam") can't locate libpam on
    # NixOS, so pin it to the store path.
    python-pam = prev.python-pam.overrideAttrs (old: {
      postInstall = (old.postInstall or "") + ''
        substituteInPlace "$out/${python.sitePackages}/pam/__internals.py" \
          --replace-fail 'find_library("pam")' '"${pkgs.pam}/lib/libpam.so"' \
          --replace-fail 'find_library("pam_misc")' '"${pkgs.pam}/lib/libpam_misc.so"'
      '';
    });

    # dbus-python and PyGObject build from sdist with meson-python; that build
    # backend (resolveBuildSystem) plus pkg-config and the C libraries must be on
    # the build inputs, otherwise the sdist build fails with "No module named
    # 'mesonpy'".
    dbus-python = prev.dbus-python.overrideAttrs (old: {
      nativeBuildInputs =
        (old.nativeBuildInputs or [])
        ++ [ pkgs.pkg-config pkgs.ninja ]
        ++ final.resolveBuildSystem { meson-python = []; };
      buildInputs = (old.buildInputs or []) ++ [ pkgs.dbus pkgs.glib ];
    });

    pygobject = prev.pygobject.overrideAttrs (old: {
      nativeBuildInputs =
        (old.nativeBuildInputs or [])
        ++ [ pkgs.pkg-config pkgs.ninja ]
        ++ final.resolveBuildSystem { meson-python = []; };
      buildInputs =
        (old.buildInputs or [])
        ++ [ pkgs.glib pkgs.gobject-introspection pkgs.cairo pkgs.python313Packages.pycairo ];
    });

    # evdev builds a C extension from sdist: it needs the setuptools backend, the
    # kernel input headers on the compiler path (for build_ext), and its setup.py
    # only searches /usr/include for linux/input.h — repoint that at linuxHeaders.
    evdev = prev.evdev.overrideAttrs (old: {
      nativeBuildInputs =
        (old.nativeBuildInputs or [])
        ++ final.resolveBuildSystem { setuptools = []; };
      buildInputs = (old.buildInputs or []) ++ [ pkgs.linuxHeaders ];
      postPatch = (old.postPatch or "") + ''
        substituteInPlace setup.py \
          --replace-fail 'include_paths.add("/usr/include")' 'include_paths.add("${pkgs.linuxHeaders}/include")'
      '';
    });

    # pycairo builds from sdist with meson-python (pulled in by pygobject's
    # cairo support); same meson stack as dbus-python/pygobject.
    pycairo = prev.pycairo.overrideAttrs (old: {
      nativeBuildInputs =
        (old.nativeBuildInputs or [])
        ++ [ pkgs.pkg-config pkgs.ninja ]
        ++ final.resolveBuildSystem { meson-python = []; };
      buildInputs = (old.buildInputs or []) ++ [ pkgs.cairo ];
    });

    # Legacy setup.py packages (no [build-system]) need the setuptools backend
    # provided explicitly, else the sdist build fails with "No module named
    # 'setuptools'".
    pidng = prev.pidng.overrideAttrs (old: {
      nativeBuildInputs =
        (old.nativeBuildInputs or [])
        ++ final.resolveBuildSystem { setuptools = []; };
    });

    adafruit-extended-bus = prev.adafruit-extended-bus.overrideAttrs (old: {
      nativeBuildInputs =
        (old.nativeBuildInputs or [])
        ++ final.resolveBuildSystem { setuptools = []; };
    });

    # cedar-solve declares the setuptools.build_meta backend but ships no
    # setuptools in its build env, so the sdist build fails with "No module
    # named 'setuptools'" — provide the backend like the other legacy packages.
    cedar-solve = prev.cedar-solve.overrideAttrs (old: {
      nativeBuildInputs =
        (old.nativeBuildInputs or [])
        ++ final.resolveBuildSystem { setuptools = []; };
    });

    rpi-gpio = prev.rpi-gpio.overrideAttrs (old: {
      nativeBuildInputs =
        (old.nativeBuildInputs or [])
        ++ final.resolveBuildSystem { setuptools = []; };
      # RPi.GPIO's C module init aborts with "This module can only be run on a
      # Raspberry Pi!" when the board revision is in neither the device tree
      # nor /proc/cpuinfo — the case on a mainline-DT arm64 NixOS Pi 4. Without
      # this every importer (adafruit-blinka -> board -> RPi.GPIO) crashes and
      # the whole app crash-loops. Patch in a /proc/device-tree/model fallback.
      postPatch =
        (old.postPatch or "")
        + ''
          patch -p1 < ${./rpi-gpio-pi-detect.patch}
        '';
    });

    # picamera2 installs from a py3-none-any wheel (no source patchPhase to
    # hook), so patch the installed module in $out. It imports its DRM (pykms)
    # and Qt preview backends unconditionally; the headless device has neither,
    # so `import picamera2` dies on a missing 'pykms' and the camera process
    # crash-loops. PiFinder only uses NullPreview, so make those optional.
    picamera2 = prev.picamera2.overrideAttrs (old: {
      postInstall =
        (old.postInstall or "")
        + ''
          f=$(find "$out" -path '*/picamera2/previews/__init__.py' | head -1)
          if [ -z "$f" ]; then
            echo "picamera2: previews/__init__.py not found under $out" >&2
            exit 1
          fi
          echo "picamera2: patching $f"
          patch "$f" < ${./picamera2-optional-previews.patch}
        '';
    });

    # No aarch64 wheel, so it builds from sdist on the Pi (fine on x86 via wheel).
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

    spidev = prev.spidev.overrideAttrs (old: {
      nativeBuildInputs =
        (old.nativeBuildInputs or [])
        ++ final.resolveBuildSystem { setuptools = []; };
    });

    # The manylinux pygame wheel bundles libSDL2, which dlopen()s libX11 /
    # libwayland / libxkbcommon / libGL / libdecor at runtime instead of listing
    # them as NEEDED, so autoPatchelf never discovers them. On a Nix host those
    # libraries aren't on the loader path, so SDL falls back to the "offscreen"
    # video driver and the emulator window never opens. Append them to the
    # runpath so SDL can load its x11/wayland backends. Dev-only (pulled in via
    # luma-emulator); pygame is not in the Pi runtime env.
    pygame = prev.pygame.overrideAttrs (old: {
      appendRunpaths = map (p: "${lib.getLib p}/lib") [
        pkgs.xorg.libX11
        pkgs.xorg.libXext
        pkgs.xorg.libXcursor
        pkgs.xorg.libXrandr
        pkgs.xorg.libXi
        pkgs.xorg.libXfixes
        pkgs.libxrender
        pkgs.libxscrnsaver
        pkgs.libxinerama
        pkgs.libxkbcommon
        pkgs.wayland
        pkgs.libGL
        pkgs.libdecor
      ];
    });

    # adafruit-blinka's wheel vendors prebuilt libgpiod_pulsein helpers for
    # non-Pi SoCs (amlogic, etc.) that link libgpiod.so.2. PiFinder never uses
    # them (BNO055 is I2C), so don't fail auto-patchelf on that missing lib.
    adafruit-blinka = prev.adafruit-blinka.overrideAttrs (old: {
      autoPatchelfIgnoreMissingDeps =
        (old.autoPatchelfIgnoreMissingDeps or []) ++ [ "libgpiod.so.2" ];
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
