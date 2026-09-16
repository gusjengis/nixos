{
  pkgs,
  ...
}:

let
  chromiumPkg = (pkgs.chromium.override { enableWideVine = true; });
in
{
  programs.chromium = {
    enable = true;
    package = chromiumPkg;
    commandLineArgs = [
      "--ozone-platform=wayland"
      "--ignore-gpu-blocklist"
      "--hide-crash-restore-bubble"
      "--disable-features=WaylandWpColorManagerV1"
      # "--enable-unsafe-webgpu"
    ];
    extensions = [
      "iobmefdldoplhmonnnkchglfdeepnfhd" # Google Search Keyboard Shortcuts
      "eimadpbcbfnmbkopoojfekhnkhdbieeh" # Dark Reader
      "jpkfgepcmmchgfbjblnodjhldacghenp" # Pie Adblock
      "aeblfdkhhhdcdjpifhhbdiojplfjncoa" # 1Password
      "eiimnmioipafcokbfikbljfdeojpcgbh" # BlockSite
      "mgngbgbhliflggkamjnpdmegbkidiapm" # Remove YouTube Shorts
      "lcpclaffcdiihapebmfgcmmplphbkjmd" # Block YouTube Feed
      "khncfooichmfjbepaaaebmommgaepoid" # Unhook
    ];
  };
}
