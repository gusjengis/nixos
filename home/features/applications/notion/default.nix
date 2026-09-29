{
  config,
  pkgs,
  lib,
  ...
}:

{
  config = lib.mkIf config.desktopEnv.enable {
    home.packages = [ pkgs.notion ];

    # home.activation.createObsidianVaultDirectory = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    #   mkdir -p "${config.home.homeDirectory}/Documents/Obsidian"
    # '';
  };
}
