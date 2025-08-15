# Edit this configuration file to define what should be installed on
# your system.  Help is available in the configuration.nix(5) man page
# and in the NixOS manual (accessible by running ‘nixos-help’).

{
  config,
  inputs,
  pkgs,
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

  networking.hostName = "nixos"; # Define your hostname.

  # FUCK steam
  steam.enable = false;

  # networking.wireless.enable = true; # Enables wireless support via wpa_supplicant.
  # networking.wireless.networks = {
  #   "Casa de la Muerte" = {
  #     psk = "crackerbox";
  #   };
  #   "Anetwork" = {
  #     psk = "prbv7532";
  #   };
  # };
  services.xserver.excludePackages = [
    # pkgs.xterm
    pkgs.nano
  ];

  # Enable networking
  networking.networkmanager.enable = true;
  networking.firewall.allowedTCPPorts = [
    47984
    47985
    47986
    47987
    47988
    47989
    47990
    48010
  ];
  networking.firewall.allowedUDPPorts = [
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

  services.avahi.publish.enable = true;
  services.avahi.publish.userServices = true;

  # Set your time zone.
  time.timeZone = "America/Los_Angeles";

  # Select internationalisation properties.
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

  # Enable the X11 windowing system.
  services.xserver.enable = true;
  services.xserver.displayManager.lightdm.enable = false;
  services.udisks2.enable = true;
  services.gvfs.enable = true;

  # Configure keymap in X11
  services.xserver.xkb = {
    layout = "us";
    variant = "";
  };

  # Enable CUPS to print documents.
  services.printing.enable = true;

  # Enable sound with pipewire.
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

  # Allow unfree packages
  nixpkgs.config.allowUnfree = true;

  # List packages installed in system profile. To search, run:
  # $ nix search wget
  environment.systemPackages = with pkgs; [
    zulu8
    prismlauncher
    atlauncher
    roslyn-ls
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
  ];

  fonts.packages =
    with pkgs;
    [ cozette ] ++ builtins.filter lib.attrsets.isDerivation (builtins.attrValues pkgs.nerd-fonts);

  xdg.portal.enable = true;

  environment.sessionVariables.NIXOS_OZONE_WL = "1";

  environment.sessionVariables = {
    EDITOR = "nvim";
    TERMINAL = "kitty";
  };

  system.stateVersion = "25.05";

  services.gnome.core-apps.enable = true;
  # Enable automatic login for the user.
  services.displayManager.autoLogin.enable = true;
  services.displayManager.autoLogin.user = "gusjengis";
}
