{pkgs}: {
  deps = [
    pkgs.nss
    pkgs.nspr
    pkgs.at-spi2-atk
    pkgs.cups
    pkgs.dbus
    pkgs.expat
    pkgs.xorg.libX11
    pkgs.xorg.libXcomposite
    pkgs.xorg.libXdamage
    pkgs.xorg.libXext
    pkgs.xorg.libXfixes
    pkgs.xorg.libXrandr
    pkgs.xorg.libxcb
    pkgs.libxkbcommon
    pkgs.alsa-lib
    pkgs.pango
    pkgs.cairo
    pkgs.gdk-pixbuf
    pkgs.atk
    pkgs.mesa
    pkgs.libdrm
    pkgs.libgbm
    pkgs.eudev
    pkgs.glib
  ];
}
