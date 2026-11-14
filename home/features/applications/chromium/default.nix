{
  config,
  pkgs,
  repoRoot,
  ...
}:

let
  chromiumPkg = import ./package.nix { inherit pkgs; };
  menlo = builtins.path { path = ./fonts/Menlo.ttc; name = "Menlo.ttc"; };
in
{
  home.packages = [
    (pkgs.callPackage ../../../packages/sf-pro.nix { })
    (import ./fonts/package.nix { inherit pkgs; })
    (pkgs.runCommand "chromium-macos-menlo" { } ''
      install -Dm644 ${menlo} "$out/share/fonts/truetype/Menlo.ttc"
    '')
  ];
  xdg.configFile."fontconfig/conf.d/61-chromium-ui.conf".source =
    config.lib.file.mkOutOfStoreSymlink
      "${repoRoot}/home/features/applications/chromium/fonts/61-chromium-ui.conf";
  programs.chromium = {
    enable = true;
    package = chromiumPkg;
    commandLineArgs = [
      "--ozone-platform=wayland"
      "--ignore-gpu-blocklist"
      "--hide-crash-restore-bubble"
      "--force-dark-mode"
      "--disable-features=WaylandWpColorManagerV1"
      # "--enable-unsafe-webgpu"
    ];
    extensions = [
      "cbghhgpcnddeihccjmnadmkaejncjndb" # Vencord Web (Discord webapp)
      "iobmefdldoplhmonnnkchglfdeepnfhd" # Google Search Keyboard Shortcuts
      "eimadpbcbfnmbkopoojfekhnkhdbieeh" # Dark Reader
      "aeblfdkhhhdcdjpifhhbdiojplfjncoa" # 1Password
      "eiimnmioipafcokbfikbljfdeojpcgbh" # BlockSite
      "mgngbgbhliflggkamjnpdmegbkidiapm" # Remove YouTube Shorts
      "lcpclaffcdiihapebmfgcmmplphbkjmd" # Block YouTube Feed
      "khncfooichmfjbepaaaebmommgaepoid" # Unhook
      "ddkjiahejlhfcafbddmgiahcphecmpfh" # uBlock Origin Lite
    ];
  };
}
