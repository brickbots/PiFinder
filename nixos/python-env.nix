{ config, lib, pkgs, ... }:
let
  python = pkgs.python312;

  pifinderPython = python.override {
    packageOverrides = self: super: {
      # --- Pure Python, trivial packages ---

      sh = self.buildPythonPackage rec {
        pname = "sh";
        version = "1.14.3";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-5ARbbHMtnOddVxx59awiNO3Zrk9fqdWbCXBQgr3KGMc=";
        };
        doCheck = false;
      };

      gpsdclient = self.buildPythonPackage rec {
        pname = "gpsdclient";
        version = "1.3.2";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-cKSWVQqXR9/14OULPJWm4dyrnYQoYJl+lRIHZ+IGCno=";
        };
        doCheck = false;
      };

      rpi-hardware-pwm = self.buildPythonPackage rec {
        pname = "rpi-hardware-pwm";
        version = "0.3.0";
        src = pkgs.fetchurl {
          url = "https://files.pythonhosted.org/packages/be/0c/4308050d8b6bbe24e8e54b38e48b287b1e356efce33cd485ee4387fc92a9/rpi_hardware_pwm-0.3.0.tar.gz";
          hash = "sha256-HshwYzp5XpijEGhWXwZ/gvZKjhZ4BpvPjdcC+i+zGyY=";
        };
        doCheck = false;
      };

      dataclasses-json = self.buildPythonPackage rec {
        pname = "dataclasses-json";
        version = "0.6.7";
        format = "pyproject";
        src = pkgs.fetchurl {
          url = "https://files.pythonhosted.org/packages/64/a4/f71d9cf3a5ac257c993b5ca3f93df5f7fb395c725e7f1e6479d2514173c3/dataclasses_json-0.6.7.tar.gz";
          hash = "sha256-trPlKCZupFuVNSI7xTymRfUgiDPCkinoR7PyahzFX8A=";
        };
        nativeBuildInputs = [ self.poetry-core ];
        propagatedBuildInputs = [
          self.marshmallow
          self.typing-inspect
        ];
        postPatch = ''
          substituteInPlace pyproject.toml \
            --replace-fail 'requires = ["poetry-core>=1.2.0", "poetry-dynamic-versioning"]' 'requires = ["poetry-core>=1.2.0"]' \
            --replace-fail 'build-backend = "poetry_dynamic_versioning.backend"' 'build-backend = "poetry.core.masonry.api"'
        '';
        doCheck = false;
      };

      # --- C extension packages ---

      RPi-GPIO = self.buildPythonPackage rec {
        pname = "RPi.GPIO";
        version = "0.7.1";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-zWHEsDw3tiu6SlrP6phidJwzxhjgKV5+kKpHE/s3O3A=";
        };
        doCheck = false;
      };

      # --- Adafruit chain: platformdetect -> pureio -> blinka -> sensors ---

      # CircuitPython typing stubs (required for Python 3.12+ type annotation evaluation)
      adafruit-circuitpython-typing = self.buildPythonPackage rec {
        pname = "adafruit-circuitpython-typing";
        version = "1.12.3";
        format = "pyproject";
        src = pkgs.fetchurl {
          url = "https://files.pythonhosted.org/packages/65/a2/40a3440aed2375371507af668570b68523ee01db9c25c47ce5a05883170e/adafruit_circuitpython_typing-1.12.3.tar.gz";
          hash = "sha256-Y/GW+DTkeEK81M+MN6qgxh4a610H8FbIdfwwFs2pGhI=";
        };
        nativeBuildInputs = [ self.setuptools-scm ];
        propagatedBuildInputs = [ self.typing-extensions ];
        doCheck = false;
        # Skip runtime dependency check - optional deps are handled by blinka chain
        dontCheckRuntimeDeps = true;
      };

      adafruit-platformdetect = self.buildPythonPackage rec {
        pname = "Adafruit-PlatformDetect";
        version = "3.73.0";
        format = "pyproject";
        src = pkgs.fetchurl {
          url = "https://files.pythonhosted.org/packages/3c/83/79eb6746d01d64bd61f02b12a2637fad441f7823a4f540842e0a47dbcfd8/adafruit_platformdetect-3.73.0.tar.gz";
          hash = "sha256-IwkJityP+Hs9mkpdOu6+P3t/VasOE9Get1/6hl82+rg=";
        };
        nativeBuildInputs = [ self.setuptools-scm ];
        doCheck = false;
      };

      adafruit-pureio = self.buildPythonPackage rec {
        pname = "Adafruit-PureIO";
        version = "1.1.11";
        format = "pyproject";
        src = pkgs.fetchurl {
          url = "https://files.pythonhosted.org/packages/e5/b7/f1672435116822079bbdab42163f9e6424769b7db778873d95d18c085230/Adafruit_PureIO-1.1.11.tar.gz";
          hash = "sha256-xM+7NlcxlC0fEJKhFvR9/a4K7xjFsn8QcrWCStXqjHw=";
        };
        nativeBuildInputs = [ self.setuptools-scm ];
        doCheck = false;
      };

      adafruit-blinka = self.buildPythonPackage rec {
        pname = "Adafruit-Blinka";
        version = "8.47.0";
        format = "pyproject";
        src = pkgs.fetchurl {
          url = "https://files.pythonhosted.org/packages/4a/30/84193a19683732387ec5f40661b589fcee29e0ab47c1e7dee36fb92efe9b/adafruit_blinka-8.47.0.tar.gz";
          hash = "sha256-Q2qFasw4v5xTRtuMQTuiraledi9qqXp9viOENMy8hRk=";
        };
        nativeBuildInputs = [ self.setuptools-scm ];
        propagatedBuildInputs = [
          self.RPi-GPIO
          self.adafruit-platformdetect
          self.adafruit-pureio
          self.adafruit-circuitpython-typing
        ];
        pythonRelaxDeps = true;
        pythonRemoveDeps = [ "binho-host-adapter" "pyftdi" "sysv-ipc" ];
        doCheck = false;
      };

      adafruit-circuitpython-busdevice = self.buildPythonPackage rec {
        pname = "adafruit-circuitpython-busdevice";
        version = "5.2.9";
        format = "pyproject";
        src = pkgs.fetchurl {
          url = "https://files.pythonhosted.org/packages/a8/04/cf8d2ebfe0d171b7c8fe3425f1e2e80ed59738855d419e5486f5d2fa9145/adafruit_circuitpython_busdevice-5.2.9.tar.gz";
          hash = "sha256-n5w984UJFBDaxZYZGOR17Ij67X/1Q61tdCCPCMJWZRM=";
        };
        nativeBuildInputs = [ self.setuptools-scm ];
        propagatedBuildInputs = [
          self.adafruit-blinka
          self.adafruit-circuitpython-typing
        ];
        doCheck = false;
      };

      adafruit-circuitpython-register = self.buildPythonPackage rec {
        pname = "adafruit-circuitpython-register";
        version = "1.10.0";
        format = "pyproject";
        src = pkgs.fetchurl {
          url = "https://files.pythonhosted.org/packages/0f/f1/b7e16545dac1056227ca9c612966ec26d69a04a99df6892aec27a71884af/adafruit_circuitpython_register-1.10.0.tar.gz";
          hash = "sha256-vH6191d2bxAqhyZXPgylwp6h1+UBweN1nGxOnhNmD3o=";
        };
        nativeBuildInputs = [ self.setuptools-scm ];
        propagatedBuildInputs = [
          self.adafruit-blinka
          self.adafruit-circuitpython-busdevice
          self.adafruit-circuitpython-typing
        ];
        doCheck = false;
      };

      adafruit-circuitpython-bno055 = self.buildPythonPackage rec {
        pname = "adafruit-circuitpython-bno055";
        version = "5.4.16";
        format = "pyproject";
        src = pkgs.fetchurl {
          url = "https://files.pythonhosted.org/packages/8d/20/ad6bb451c5bf228af869bf045d4fc415174e7c042dfc1d998e9c0bc8ad21/adafruit_circuitpython_bno055-5.4.16.tar.gz";
          hash = "sha256-kL/bz689GF/sZxgbzv+bEPQ4F5zQqjl+k4ctSwlK3aA=";
        };
        nativeBuildInputs = [ self.setuptools-scm ];
        propagatedBuildInputs = [
          self.adafruit-blinka
          self.adafruit-circuitpython-busdevice
          self.adafruit-circuitpython-register
          self.adafruit-circuitpython-typing
        ];
        doCheck = false;
      };

      # --- Display stack: luma.core -> luma.oled, luma.lcd ---

      luma-core = self.buildPythonPackage rec {
        pname = "luma.core";
        version = "2.4.2";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-ljwmQWTUN09UnVfbCVmeDKRYzqG9BeFpOYl2Gb5Obb0=";
        };
        propagatedBuildInputs = [
          self.pillow
          self.smbus2
          self.pyftdi
          self.cbor2
          self.deprecated
        ];
        doCheck = false;
      };

      luma-oled = self.buildPythonPackage rec {
        pname = "luma.oled";
        version = "3.13.0";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-fioNakyWjGSYAlXWgewnkU2avVpmqQGbKJvzrQUMISU=";
        };
        propagatedBuildInputs = [ self.luma-core ];
        doCheck = false;
      };

      luma-lcd = self.buildPythonPackage rec {
        pname = "luma.lcd";
        version = "2.11.0";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-1GBE6W/TmUPr5Iph51M3FXG+FJekvqlrcuOpxzL77uQ=";
        };
        propagatedBuildInputs = [ self.luma-core ];
        doCheck = false;
      };

      # --- DeepSkyLog API ---

      pydeepskylog = self.buildPythonPackage rec {
        pname = "pydeepskylog";
        version = "1.6";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-3erm0ASBfPtQ1cngzsqkZUrnKoLNIBu8U1D6iA4ePmE=";
        };
        propagatedBuildInputs = [ self.requests ];
        doCheck = false;
      };

      # --- PAM bindings for password verification ---

      python-pam = self.buildPythonPackage rec {
        pname = "python-pam";
        version = "2.0.2";
        format = "pyproject";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-lyNSNbqbgtuugGjRCZUIRVlJsnX3cnPKIv29ix+12VA=";
        };
        nativeBuildInputs = [ self.setuptools self.six ];
        # python-pam uses ctypes to load libpam.so from __internals.py
        postPatch = ''
          substituteInPlace src/pam/__internals.py \
            --replace-fail 'find_library("pam")' '"${pkgs.pam}/lib/libpam.so"' \
            --replace-fail 'find_library("pam_misc")' '"${pkgs.pam}/lib/libpam_misc.so"'
        '';
        doCheck = false;
      };

      # --- pidng (for picamera2 DNG support) ---

      pidng = self.buildPythonPackage rec {
        pname = "pidng";
        version = "4.0.9";
        src = pkgs.fetchurl {
          url = "https://files.pythonhosted.org/packages/source/p/pidng/pidng-4.0.9.tar.gz";
          hash = "sha256-Vg6wCAhvinFf2eGrmYgXp9TIUAp/Fhuc5q9asnUB+Cw=";
        };
        propagatedBuildInputs = [ self.numpy ];
        doCheck = false;
      };

      # --- simplejpeg (fast JPEG encode/decode for picamera2) ---
      # Use prebuilt wheel - source build tries to download libjpeg-turbo

      simplejpeg = self.buildPythonPackage rec {
        pname = "simplejpeg";
        version = "1.9.0";
        format = "wheel";
        src = pkgs.fetchurl {
          url = "https://files.pythonhosted.org/packages/75/c1/0cbf167e3efa32adfbb0674a3504eb118cc5bdc372a44ee937c30324188e/simplejpeg-1.9.0-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl";
          hash = "sha256-CKszfKOybXVi9a1oarjzlm+yBvztYH0kjmk8vFf8U7M=";
        };
        propagatedBuildInputs = [ self.numpy ];
        doCheck = false;
      };

      # --- prctl bindings (for picamera2) ---

      python-prctl = self.buildPythonPackage rec {
        pname = "python-prctl";
        version = "1.8.1";
        src = pkgs.fetchurl {
          url = "https://files.pythonhosted.org/packages/source/p/python-prctl/python-prctl-1.8.1.tar.gz";
          hash = "sha256-tMqaJafU8azk//0fOi5k71II/gX5KfPt1eJwgcp+Z84=";
        };
        buildInputs = [ pkgs.libcap ];
        doCheck = false;
      };

      # --- libinput bindings (rebuild: 2026-02-03 fix lib path) ---

      python-libinput = self.buildPythonPackage rec {
        pname = "python-libinput";
        version = "0.3.0a0";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-fj08l4aqp5vy8UYBZIWBtGJLaS0/DZGZkC0NCDQhkwI=";
        };
        buildInputs = [ pkgs.libinput pkgs.systemd ];
        nativeBuildInputs = [ pkgs.pkg-config ];
        propagatedBuildInputs = [ self.cffi ];
        # imp module removed in Python 3.12; also patch library paths for NixOS
        postPatch = ''
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
        doCheck = false;
      };

      v4l2-python3 = self.buildPythonPackage rec {
        pname = "v4l2-python3";
        version = "0.3.4";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-YliResgEmsaYcaXg39bYnVXJ5/gOgSwe+LqIeb2hxYc=";
        };
        doCheck = false;
      };

      # --- videodev2 (V4L2 ctypes bindings for picamera2) ---

      videodev2 = self.buildPythonPackage rec {
        pname = "videodev2";
        version = "0.0.4";
        format = "wheel";
        src = pkgs.fetchurl {
          url = "https://files.pythonhosted.org/packages/68/30/4982441a03860ab8f656702d8a2c13d0cf6f56d65bfb78fe288028dcb473/videodev2-0.0.4-py3-none-any.whl";
          hash = "sha256-0196s53bBtUP7Japm/yNW4tSW8fqA3iCWdOGOT8aZLo=";
        };
        doCheck = false;
      };

      # --- picamera2 (depends on libcamera with Python bindings) ---

      picamera2 = self.buildPythonPackage rec {
        pname = "picamera2";
        version = "0.3.22";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-iShpgUNCu8uHS7jeehtgWJhEm/UhJjn0bw2qpkbWgy0=";
        };
        # Make DrmPreview import optional - pykms (kmsxx Python bindings) not
        # available in nixpkgs. PiFinder uses NullPreview anyway.
        postPatch = ''
          substituteInPlace picamera2/previews/__init__.py \
            --replace-fail 'from .drm_preview import DrmPreview' \
            'try:
    from .drm_preview import DrmPreview
except ImportError:
    DrmPreview = None'
        '';
        propagatedBuildInputs = [
          self.numpy
          self.pillow
          self.piexif
          self.v4l2-python3
          self.videodev2       # V4L2 ctypes bindings (required by picamera2)
          self.pidng           # DNG support
          self.simplejpeg      # Fast JPEG encoding
          self.python-prctl    # Process control
          pkgs.libcamera       # needs pycamera enabled (see overlay)
          # av, libarchive-c, jsonschema, tqdm are in the main env
        ];
        # libcamera Python bindings must be on PYTHONPATH
        postFixup = ''
          wrapPythonProgramsIn "$out" "$out ${pkgs.libcamera}/lib/python3.12/site-packages"
        '';
        doCheck = false;
      };
    };
  };

  env = pifinderPython.withPackages (ps: with ps; [
    # Packages from nixpkgs (already available)
    numpy
    scipy
    scikit-learn
    pillow
    pandas
    grpcio
    protobuf
    bottle
    cheroot
    requests
    pytz
    skyfield
    tqdm
    pyjwt
    aiofiles
    json5
    smbus2
    spidev          # SPI interface for display
    pygobject3      # GLib bindings for NetworkManager
    av              # PyAV - ffmpeg bindings for picamera2 encoders
    dbus-python     # D-Bus for hostname/reboot/shutdown
    timezonefinder  # Timezone lookup from GPS coordinates
    jsonschema      # For picamera2 configuration validation
    libarchive-c    # For picamera2 archive handling

    # Custom packaged (from overlay above)
    sh
    gpsdclient
    rpi-hardware-pwm
    dataclasses-json
    adafruit-blinka
    adafruit-circuitpython-bno055
    luma-oled
    luma-lcd
    python-libinput
    python-pam
    python-prctl
    pidng
    simplejpeg
    videodev2       # V4L2 ctypes bindings for picamera2
    pydeepskylog
    RPi-GPIO
    picamera2
  ]);
in {
  # libcamera overlay — enable Python bindings for picamera2
  nixpkgs.overlays = [(final: prev: {
    libcamera = prev.libcamera.overrideAttrs (old: {
      mesonFlags = (old.mesonFlags or []) ++ [
        "-Dpycamera=enabled"
      ];
      buildInputs = (old.buildInputs or []) ++ [
        final.python312
        final.python312.pkgs.pybind11
      ];
    });
  })];

  environment.systemPackages = [
    env
    pkgs.gobject-introspection  # GI typelibs
    pkgs.networkmanager         # NM-1.0 typelib for gi.repository.NM
    pkgs.libcamera              # for picamera2 Python bindings
    pkgs.gpsd                   # for gpsctl (runtime GPS baud rate changes)
  ];

  # Ensure GI_TYPELIB_PATH includes NetworkManager typelib
  environment.sessionVariables.GI_TYPELIB_PATH = lib.makeSearchPath "lib/girepository-1.0" [
    pkgs.networkmanager
    pkgs.glib
  ];

  # Add libcamera Python bindings to PYTHONPATH (for picamera2)
  environment.sessionVariables.PYTHONPATH = "${pkgs.libcamera}/lib/python3.12/site-packages";

  # Export the Python environment for use by services.nix
  _module.args.pifinderPythonEnv = env;
}
