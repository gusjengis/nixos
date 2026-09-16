{
  config,
  pkgs,
  repoRoot,
  ...
}:
let
  configRoot = "${repoRoot}/home/features/terminal/kitty";
in
{
  home.packages = [ pkgs.kitty ];

  xdg.configFile = {
    "kitty/kitty.conf".source = config.lib.file.mkOutOfStoreSymlink "${configRoot}/kitty.conf";
    "kitty/github_dark.conf".source =
      config.lib.file.mkOutOfStoreSymlink "${configRoot}/github_dark.conf";
  };
}
