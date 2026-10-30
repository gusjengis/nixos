{
  config,
  pkgs,
  lib,
  repoRoot,
  ...
}:
let
  configRoot = "${repoRoot}/home/features/files/documents";
in
{
  home.packages =
    with pkgs;
    [
      kdePackages.filelight
      libreoffice
      qimgv
      zathura
    ]
    ++ lib.optionals config.personalDesktop.enable [ pkgs.f3d ];

  xdg.configFile."zathura/zathurarc".source =
    config.lib.file.mkOutOfStoreSymlink "${configRoot}/zathurarc";

  xdg.configFile."f3d/config.json" = lib.mkIf config.personalDesktop.enable {
    source = config.lib.file.mkOutOfStoreSymlink "${configRoot}/f3d/config.json";
  };
}
