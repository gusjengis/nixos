{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
  ];

  services.keyd = {
    enable = true;
    keyboards = {
      default = {
        extraConfig = ''
          [ids]
            0001:0001:70533846
            04f3:0020:e1b87864
          [main]
            capslock = overload(control, esc)
            rightmouse = backspace
            middlemouse = leftmeta
            sysrq = f24

        '';
      };
    };
  };

  system.stateVersion = "25.11"; # Did you read the comment?
}
