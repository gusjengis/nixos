{
  pkgs,
  lib,
  ...
}:

let
  sharedKeyPath = "${toString ./../keys/shared_ed25519.pub}";
in
{
  # Define a user account. Don't forget to set a password with ‘passwd’.
  users.users.gusjengis = {
    isNormalUser = true;
    description = "Anthony Green";
    extraGroups = [
      "networkmanager"
      "wheel"
      "dialout"
      "docker"
    ];
    packages = with pkgs; [ home-manager ];
    openssh.authorizedKeys.keys = lib.optionals (builtins.pathExists sharedKeyPath) [
      (lib.strings.removeSuffix "\n" (builtins.readFile sharedKeyPath))
    ];
  };
}
