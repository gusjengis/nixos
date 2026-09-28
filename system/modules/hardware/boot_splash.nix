{
  config,
  lib,
  pkgs,
  ...
}:
let
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
      theme = ./boot-splash/grub;
      # GRUB does not draw its theme until the menu opens; gfxterm displays this during hidden timeout.
      splashImage = ./boot-splash/grub/background.png;
      backgroundColor = "#000000";
      timeoutStyle = "hidden";
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
  };
}
