{ config, repoRoot, ... }:
let
  configRoot = "${repoRoot}/home/features/files/default-apps";
in
{
  xdg.configFile = {
    "mimeapps.list".source = config.lib.file.mkOutOfStoreSymlink "${configRoot}/mimeapps.list";
    "xfce4/helpers.rc".source = config.lib.file.mkOutOfStoreSymlink "${configRoot}/helpers.rc";
  };
}
