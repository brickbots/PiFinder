{ pkgs ? import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/nixos-24.05.tar.gz") {} }:

let
  inherit (pkgs) lib stdenv;
in
pkgs.mkShell {
  buildInputs = with pkgs; [
    python39
    python39Packages.pip
    python39Packages.virtualenv

    # Build dependencies for native extensions
    gcc
    pkg-config
    zlib
    libjpeg
    libpng
    freetype
    openblas
    lapack

    # For luma.oled/lcd (display libs)
    libusb1

    # For pygame
    SDL2
    SDL2_image
    SDL2_mixer
    SDL2_ttf
  ]
  ++ lib.optionals stdenv.isLinux [
    linuxHeaders
    wayland
    libxkbcommon
    libGL
    mesa
    # XWayland support
    xorg.libX11
    xorg.libXcursor
    xorg.libXrandr
    xorg.libXi
  ]
  ++ lib.optionals stdenv.isDarwin [
    darwin.apple_sdk.frameworks.Cocoa
    darwin.apple_sdk.frameworks.CoreVideo
    darwin.apple_sdk.frameworks.IOKit
  ];

  shellHook = ''
    export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath ([
      pkgs.stdenv.cc.cc.lib
      pkgs.zlib
      pkgs.libjpeg
      pkgs.libpng
      pkgs.freetype
      pkgs.openblas
      pkgs.lapack
      pkgs.SDL2
      pkgs.SDL2_image
      pkgs.SDL2_mixer
      pkgs.SDL2_ttf
    ] ++ lib.optionals stdenv.isLinux [
      pkgs.wayland
      pkgs.libxkbcommon
      pkgs.libGL
      pkgs.mesa
      pkgs.xorg.libX11
      pkgs.xorg.libXcursor
      pkgs.xorg.libXrandr
      pkgs.xorg.libXi
    ])}:$LD_LIBRARY_PATH"
  '' + lib.optionalString stdenv.isLinux ''
    export C_INCLUDE_PATH="${pkgs.linuxHeaders}/include:$C_INCLUDE_PATH"
    export LIBGL_DRIVERS_PATH="${pkgs.mesa.drivers}/lib/dri"
    export __EGL_VENDOR_LIBRARY_DIRS="${pkgs.mesa.drivers}/share/glvnd/egl_vendor.d"
    # Use XWayland for pygame (allows window resize on Wayland compositors)
    export SDL_VIDEODRIVER=x11
  '';
}
