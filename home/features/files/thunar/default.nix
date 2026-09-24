{
  config,
  pkgs,
  repoRoot,
  ...
}:
let
  configRoot = "${repoRoot}/home/features/files/thunar";
in
{
  home.packages = with pkgs; [
    thunar
    tumbler
    thunar-volman
    thunar-archive-plugin
    file-roller
    gvfs
    udiskie
  ];

  # Thunar's xfconf settings (e.g. menubar visibility). Linked out-of-store
  # so in-app changes (via the xfconf backend) write straight back into the
  # repo instead of a Nix store path.
  xdg.configFile."xfce4/xfconf/xfce-perchannel-xml/thunar.xml".source =
    config.lib.file.mkOutOfStoreSymlink "${configRoot}/thunar.xml";

  systemd.user.services.thunar = {
    Unit.Description = "Thunar file manager daemon";

    Service = {
      Type = "dbus";
      ExecStart = "${pkgs.thunar}/bin/Thunar --daemon";
      BusName = "org.xfce.FileManager";
      KillMode = "process";
      Restart = "on-failure";
      RestartSec = 2;
    };
  };
}
