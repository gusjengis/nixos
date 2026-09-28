{
  config,
  lib,
  pkgs,
  ...
}:
let
  finishSplash = pkgs.writeShellScriptBin "finish-boot-splash" ''
    if /run/wrappers/bin/sudo -n ${config.boot.plymouth.package}/bin/plymouth --ping >/dev/null 2>&1; then
      if [ "$#" -gt 0 ] && [ "$1" = "--prepare" ]; then
        /run/wrappers/bin/sudo -n ${config.boot.plymouth.package}/bin/plymouth display-message --text=darwin-session-ready
        sleep 0.25
        /run/wrappers/bin/sudo -n ${config.boot.plymouth.package}/bin/plymouth deactivate
      else
        /run/wrappers/bin/sudo -n ${config.boot.plymouth.package}/bin/plymouth quit --retain-splash
      fi
    fi
  '';
  theme = pkgs.runCommand "darwin-plymouth-theme" { } ''
    mkdir -p "$out/share/plymouth/themes/darwin"
    destination="$out/share/plymouth/themes/darwin"
    cp ${./boot-splash/darwin.script} "$destination/darwin.script"
    cp ${./boot-splash/logo.png} "$destination/logo.png"
    cp ${./boot-splash/progress_box.png} "$destination/progress_box.png"
    cp ${./boot-splash/progress_bar.png} "$destination/progress_bar.png"
    substitute ${./boot-splash/darwin.plymouth} "$destination/darwin.plymouth" --replace-fail '@out@' "$out"
  '';
in
{
  options.bootSplash.enable = lib.mkEnableOption "Darwin-style graphical boot for desktop machines";

  config = lib.mkIf (config.bootSplash.enable && config.grub.enable) {
    boot.loader.grub = {
      # GRUB cannot center an unscaled image during the hidden countdown.
      # Keep that frame black instead of stretching a low-resolution bitmap.
      theme = null;
      splashImage = null;
      timeoutStyle = "hidden";
      extraConfig = ''
        background_color '#000000'
        set color_normal=white/black
        set color_highlight=black/white
      '';
    };
    boot.plymouth = {
      enable = true;
      theme = "darwin";
      themePackages = [ theme ];
    };
    boot.kernelParams = [
      "quiet"
      "loglevel=3"
      "udev.log_priority=3"
      "vt.global_cursor_default=0"
    ];
    boot.consoleLogLevel = 0;
    boot.initrd.verbose = false;
    environment.systemPackages = [ finishSplash ];

    # getty@tty1 must start before Hyprland can signal readiness.
    systemd.services."getty@".serviceConfig.TTYVTDisallocate = false;
    systemd.services.plymouth-quit.wantedBy = lib.mkForce [ ];
    systemd.services.plymouth-quit-wait.wantedBy = lib.mkForce [ ];
    systemd.timers.plymouth-boot-fallback = {
      wantedBy = [ "multi-user.target" ];
      timerConfig = {
        OnActiveSec = "45s";
        Unit = "plymouth-quit.service";
      };
    };
  };
}
