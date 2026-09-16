{ ... }:

{
  nixpkgs.config = {
    permittedInsecurePackages = [
      # Added for Linux Wallpaper Engine. Neither dependency currently appears
      # in the active closure, but keep the allowances for alternate profiles.
      "libsoup-2.74.3"
      "mbedtls-2.28.10"

      # utilities/mod.nix installs this exact Ventoy release.
      "ventoy-1.1.17"
    ];
  };
}
