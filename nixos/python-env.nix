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
          hash = "sha256-FIXME";
        };
        doCheck = false;
      };

      gpsdclient = self.buildPythonPackage rec {
        pname = "gpsdclient";
        version = "1.3.2";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-FIXME";
        };
        doCheck = false;
      };

      rpi-hardware-pwm = self.buildPythonPackage rec {
        pname = "rpi-hardware-pwm";
        version = "0.2.1";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-FIXME";
        };
        doCheck = false;
      };

      dataclasses-json = self.buildPythonPackage rec {
        pname = "dataclasses-json";
        version = "0.6.7";
        format = "pyproject";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-FIXME";
        };
        nativeBuildInputs = [ self.poetry-core ];
        propagatedBuildInputs = [
          self.marshmallow
          self.typing-inspect
        ];
        doCheck = false;
      };

      # --- C extension packages ---

      RPi-GPIO = self.buildPythonPackage rec {
        pname = "RPi.GPIO";
        version = "0.7.1";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-FIXME";
        };
        doCheck = false;
      };

      # --- Adafruit chain: platformdetect -> pureio -> blinka -> sensors ---

      adafruit-platformdetect = self.buildPythonPackage rec {
        pname = "Adafruit-PlatformDetect";
        version = "3.73.0";
        format = "pyproject";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-FIXME";
        };
        nativeBuildInputs = [ self.setuptools-scm ];
        doCheck = false;
      };

      adafruit-pureio = self.buildPythonPackage rec {
        pname = "Adafruit-PureIO";
        version = "1.1.11";
        format = "pyproject";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-FIXME";
        };
        nativeBuildInputs = [ self.setuptools-scm ];
        doCheck = false;
      };

      adafruit-blinka = self.buildPythonPackage rec {
        pname = "Adafruit-Blinka";
        version = "8.47.0";
        format = "pyproject";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-FIXME";
        };
        nativeBuildInputs = [ self.setuptools-scm ];
        propagatedBuildInputs = [
          self.RPi-GPIO
          self.adafruit-platformdetect
          self.adafruit-pureio
        ];
        doCheck = false;
      };

      adafruit-circuitpython-busdevice = self.buildPythonPackage rec {
        pname = "adafruit-circuitpython-busdevice";
        version = "5.2.9";
        format = "pyproject";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-FIXME";
        };
        nativeBuildInputs = [ self.setuptools-scm ];
        propagatedBuildInputs = [ self.adafruit-blinka ];
        doCheck = false;
      };

      adafruit-circuitpython-register = self.buildPythonPackage rec {
        pname = "adafruit-circuitpython-register";
        version = "1.10.0";
        format = "pyproject";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-FIXME";
        };
        nativeBuildInputs = [ self.setuptools-scm ];
        propagatedBuildInputs = [ self.adafruit-blinka ];
        doCheck = false;
      };

      adafruit-circuitpython-bno055 = self.buildPythonPackage rec {
        pname = "adafruit-circuitpython-bno055";
        version = "5.4.16";
        format = "pyproject";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-FIXME";
        };
        nativeBuildInputs = [ self.setuptools-scm ];
        propagatedBuildInputs = [
          self.adafruit-blinka
          self.adafruit-circuitpython-busdevice
          self.adafruit-circuitpython-register
        ];
        doCheck = false;
      };

      # --- Display stack: luma.core -> luma.oled, luma.lcd ---

      luma-core = self.buildPythonPackage rec {
        pname = "luma.core";
        version = "2.4.2";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-FIXME";
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
          hash = "sha256-FIXME";
        };
        propagatedBuildInputs = [ self.luma-core ];
        doCheck = false;
      };

      luma-lcd = self.buildPythonPackage rec {
        pname = "luma.lcd";
        version = "2.12.0";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-FIXME";
        };
        propagatedBuildInputs = [ self.luma-core ];
        doCheck = false;
      };

      # --- PAM bindings for password verification ---

      python-pam = self.buildPythonPackage rec {
        pname = "python-pam";
        version = "2.0.2";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-FIXME";
        };
        # python-pam uses ctypes to load libpam.so
        postPatch = ''
          substituteInPlace src/pam/__init__.py \
            --replace 'find_library("pam")' '"${pkgs.pam}/lib/libpam.so"'
        '';
        doCheck = false;
      };

      # --- libinput bindings ---

      python-libinput = self.buildPythonPackage rec {
        pname = "python-libinput";
        version = "0.2.0";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-FIXME";
        };
        buildInputs = [ pkgs.libinput ];
        nativeBuildInputs = [ pkgs.pkg-config ];
        propagatedBuildInputs = [ self.cffi ];
        doCheck = false;
      };

      # --- picamera2 (depends on libcamera with Python bindings) ---

      picamera2 = self.buildPythonPackage rec {
        pname = "picamera2";
        version = "0.3.22";
        src = self.fetchPypi {
          inherit pname version;
          hash = "sha256-FIXME";
        };
        propagatedBuildInputs = [
          self.numpy
          self.pillow
          self.piexif
          self.simplejpeg
          self.v4l2-python3
          self.av
          pkgs.libcamera  # needs pycamera enabled (see overlay)
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
    pygobject3      # GLib bindings for NetworkManager
    dbus-python     # D-Bus for hostname/reboot/shutdown

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
  ];

  # Ensure GI_TYPELIB_PATH includes NetworkManager typelib
  environment.sessionVariables.GI_TYPELIB_PATH = lib.makeSearchPath "lib/girepository-1.0" [
    pkgs.networkmanager
    pkgs.glib
  ];

  # Export the Python environment for use by services.nix
  _module.args.pifinderPythonEnv = env;
}
