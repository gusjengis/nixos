# Chromium macOS font inputs

`Menlo.ttc` is copied from the reference Mac's `/System/Library/Fonts/Menlo.ttc`.
It supplies the actual macOS monospaced UI family instead of a Linux fallback.
SF Pro is installed through the existing `home/packages/sf-pro.nix` package.

Font roles, native PostScript names, sizes, traits, and measured metrics are
captured in `../appkit-theme.json`. macOS's private system-family name maps to
the public SF Pro family on Linux; rasterization remains Skia/FreeType.
