{
  config,
  pkgs,
  repoRoot,
  ...
}:
let
  configRoot = "${repoRoot}/home/features/files/documents";
in
{
  home.packages = with pkgs; [
    kdePackages.filelight
    libreoffice
    qimgv
    zathura
    f3d
  ];

  xdg.configFile."zathura/zathurarc".source =
    config.lib.file.mkOutOfStoreSymlink "${configRoot}/zathurarc";

  xdg.configFile."f3d/config.json".source =
    config.lib.file.mkOutOfStoreSymlink "${configRoot}/f3d/config.json";
}
