{
  config,
  lib,
  inputs,
  pkgs,
  stable,
  ...
}:
{
  imports = [
    ./users.nix
  ];

  nix.settings.experimental-features = [
    "nix-command"
    "flakes"
  ];

  systemd.services."NetworkManager-wait-online".enable = false;

  networking.firewall = {
    allowedTCPPortRanges = [
      {
        from = 1714;
        to = 1764;
      }
    ];
    allowedUDPPortRanges = [
      {
        from = 1714;
        to = 1764;
      }
    ];

    # Keep your existing specific ports if needed
    allowedTCPPorts = [
      47984
      47985
      47986
      47987
      47988
      47989
      47990
      48010
    ];
    allowedUDPPorts = [
      47998
      47999
      48000
      48001
      48002
      48003
      48004
      48005
      48006
      48007
      48008
      48009
      48010
    ];
  };

  services.udev.packages = [ pkgs.android-udev-rules ];

  services.avahi.publish.enable = true;
  services.avahi.publish.userServices = true;

  time.timeZone = "America/Los_Angeles";

  i18n.defaultLocale = "en_US.UTF-8";

  i18n.extraLocaleSettings = {
    LC_ADDRESS = "en_US.UTF-8";
    LC_IDENTIFICATION = "en_US.UTF-8";
    LC_MEASUREMENT = "en_US.UTF-8";
    LC_MONETARY = "en_US.UTF-8";
    LC_NAME = "en_US.UTF-8";
    LC_NUMERIC = "en_US.UTF-8";
    LC_PAPER = "en_US.UTF-8";
    LC_TELEPHONE = "en_US.UTF-8";
    LC_TIME = "en_US.UTF-8";
  };

  services.xserver.enable = true;
  services.xserver.displayManager.lightdm.enable = false;
  services.udisks2.enable = true;
  services.gvfs.enable = true;

  services.xserver.xkb = {
    layout = "us";
    variant = "";
  };

  services.pulseaudio.enable = false;
  security.rtkit.enable = true;
  services.pipewire = {
    enable = true;
    alsa.enable = true;
    alsa.support32Bit = true;
    pulse.enable = true;
  };

  programs.dconf.enable = true;

  hardware.bluetooth.enable = true; # enables support for Bluetooth
  hardware.bluetooth.powerOnBoot = true; # powers up the default Bluetooth controller on boot

  programs.file-roller.enable = true;
  nixpkgs.config.allowBroken = true;
  # Turn of password for sudo, so annoying
  security.sudo.extraConfig = ''
    %wheel ALL=(ALL) NOPASSWD: ALL
  '';

  nixpkgs.config.allowUnfree = true;

  environment.systemPackages = with pkgs; [
    zulu8
    prismlauncher
    atlauncher
    xdg-desktop-portal-gtk
    xdg-desktop-portal-hyprland
    vulkan-tools
    dotnetCorePackages.dotnet_9.sdk
    mermaid-cli
    nodejs_24
    unzip
    wget
    eww
    libnotify
    dunst
    pavucontrol
    wayland
    wayland-protocols
    openssl
    fd
    libxkbcommon
    libGL
    skia
    gvfs
    udiskie
    libgbm
    egl-wayland
    vulkan-loader
    libglvnd
  ];

  fonts.packages = with pkgs; [
    cozette
    carlito
    commit-mono
    nerd-fonts.meslo-lg
    fragment-mono
    helvetica-neue-lt-std
  ];

  programs.nix-ld = {
    enable = true;
  };

  xdg.portal.enable = true;

  environment.sessionVariables.NIXOS_OZONE_WL = "1";

  virtualisation.docker.enable = true;

  services.gnome.core-apps.enable = false;
  # Enable automatic login for the user.
  services.displayManager.autoLogin.enable = true;
  services.displayManager.autoLogin.user = "gusjengis";

  system.stateVersion = "25.05";

}
