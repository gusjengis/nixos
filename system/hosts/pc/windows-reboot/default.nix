{ pkgs, ... }:
let
  # Privileged code must be immutable, unlike editable application settings.
  helper = pkgs.writeScriptBin "reboot-into-windows-root" (
    "#!${pkgs.python3}/bin/python3 -I\n"
    + builtins.replaceStrings
      [ "@efibootmgr@" "@systemctl@" ]
      [ "${pkgs.efibootmgr}/bin/efibootmgr" "${pkgs.systemd}/bin/systemctl" ]
      (builtins.readFile ./reboot_windows.py)
  );
  launcher = pkgs.writeShellApplication {
    name = "reboot-into-windows";
    runtimeInputs = [ pkgs.zenity ];
    text = ''
      if ! zenity --question --title="Reboot into Windows" \
        --text="Save your work first. Reboot into Windows now?\n\nThis applies to the next boot only; your normal boot order stays unchanged." \
        --ok-label="Reboot into Windows" --cancel-label="Cancel" \
        --default-cancel --no-wrap; then
        exit 0
      fi
      if ! error=$(/run/wrappers/bin/sudo -n ${helper}/bin/reboot-into-windows-root 2>&1); then
        zenity --error --title="Could not reboot into Windows" --text="$error" --no-wrap
        exit 1
      fi
    '';
  };
  desktop = pkgs.makeDesktopItem {
    name = "reboot-into-windows";
    desktopName = "Reboot into Windows";
    comment = "Restart into Windows once, keeping the normal boot order";
    exec = "${launcher}/bin/reboot-into-windows";
    icon = "system-reboot";
    categories = [ "System" ];
    keywords = [ "Windows" "Reboot" "Restart" "Boot" ];
  };
in
{
  environment.systemPackages = [ launcher desktop ];
  security.sudo.extraRules = [
    {
      users = [ "gusjengis" ];
      commands = [
        {
          # Empty argument string forbids arguments; no general firmware access.
          command = "${helper}/bin/reboot-into-windows-root \"\"";
          options = [ "NOPASSWD" ];
        }
      ];
    }
  ];
}
