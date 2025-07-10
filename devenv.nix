{ pkgs, lib, ... }:
let
  # Use nixos-23.11 for Python 3.9 and dependencies
  oldPkgs = import (fetchTarball {
    url = "https://github.com/NixOS/nixpkgs/archive/nixos-23.11.tar.gz";
    sha256 = "1f5d2g1p6nfwycpmrnnmc2xmcszp804adp16knjvdkj8nz36y1fg";
  }) {
    system = pkgs.system;
  };
in
{
  packages = [
    oldPkgs.python39
    oldPkgs.python39Packages.pip
    oldPkgs.python39Packages.virtualenv
    oldPkgs.python39Packages.numpy
    oldPkgs.python39Packages.scipy
    oldPkgs.python39Packages.pillow
    oldPkgs.python39Packages.pygame  # Add Pygame from nixos-23.11
    oldPkgs.SDL2  # Native SDL2 with X11 support
    oldPkgs.SDL2_image
    oldPkgs.SDL2_mixer
    oldPkgs.SDL2_ttf
    oldPkgs.libGL
    oldPkgs.xorg.libX11  # X11 libraries for XWayland
    oldPkgs.xorg.libXext
    oldPkgs.xorg.libXrandr
    oldPkgs.libinput
    oldPkgs.libxkbcommon
    oldPkgs.linuxHeaders
    oldPkgs.gcc
    oldPkgs.pkg-config
    pkgs.uv  # Keep uv from the main nixpkgs
  ];

  enterShell = ''
    echo "Trying Python 3.9 from nixos-23.11..."
    python --version

    # Test if this Python 3.9 works
    python -c "print('Testing Python 3.9 functionality...')"
    python -c "import sys; print('Python path works')"

    if [ $? -eq 0 ]; then
      echo "✓ Python 3.9 is working!"

      # Set environment variables for SDL2 and X11
      export SDL_VIDEODRIVER=x11
      export DISPLAY=:0  # Ensure XWayland display is set
      export CPATH="${oldPkgs.linuxHeaders}/include:${oldPkgs.SDL2.dev}/include:${oldPkgs.xorg.libX11.dev}/include:$CPATH"
      export C_INCLUDE_PATH="${oldPkgs.linuxHeaders}/include:${oldPkgs.SDL2.dev}/include:${oldPkgs.xorg.libX11.dev}/include:$C_INCLUDE_PATH"
      export LIBRARY_PATH="${oldPkgs.SDL2}/lib:${oldPkgs.xorg.libX11}/lib:${oldPkgs.xorg.libXext}/lib:${oldPkgs.xorg.libXrandr}/lib:${oldPkgs.libGL}/lib:$LIBRARY_PATH"
      export PKG_CONFIG_PATH="${oldPkgs.SDL2.dev}/lib/pkgconfig:${oldPkgs.xorg.libX11.dev}/lib/pkgconfig:$PKG_CONFIG_PATH"

      # Set up symlink for tetra3
      if [ ! -L python/tetra3 ]; then
        ln -s ./PiFinder/tetra3/tetra3 ./python/tetra3
        echo "Created tetra3 symlink"
      fi

      # Create venv if needed
      if [ ! -d .venv ]; then
        uv venv --python ${oldPkgs.python39}/bin/python .venv
      fi

      source .venv/bin/activate
      uv pip install -r python/requirements.txt -r python/requirements_dev.txt
      # Install Pygame from source to ensure it links to system SDL2
      uv pip install pygame --no-binary pygame

      echo "Python 3.9 environment ready!"
    else
      echo "✗ Python 3.9 still broken. Need to try another approach."
    fi
  '';
}
