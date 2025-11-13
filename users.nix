{
  config,
  pkgs,
  ...
}:

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
  };

  users.users.gnometest = {
    isNormalUser = true;
    description = "Gnome Tester";
    extraGroups = [
      "networkmanager"
      "wheel"
    ];
    packages = with pkgs; [ home-manager ];
  };
}
