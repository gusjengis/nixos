# nix eval --impure --json --file home/features/desktop/test-profiles.nix
let
  flake = builtins.getFlake ("path:" + toString ../../..);
  conference = flake.homeConfigurations.agc-conference.config;
  workstation = flake.homeConfigurations.mac.config;
  withoutContexts =
    (flake.homeConfigurations.mac.extendModules {
      modules = [ { desktopContexts.enable = false; } ];
    }).config;
  names = c: map (p: p.pname or p.name) c.home.packages;
  absent = list: c: builtins.all (name: !(builtins.elem name (names c))) list;
  present = list: c: builtins.all (name: builtins.elem name (names c)) list;
  contextServices = [
    "desktop-contexts"
    "context-checkpoint"
    "context-shutdown-barrier"
  ];
in
assert conference.desktopEnv.enable;
assert !conference.desktopContexts.enable;
assert !conference.personalDesktop.enable;
assert !conference.dev.enable;
assert present [
  "hyprland"
  "zoom"
  "supernote-mirror"
  "lazygit"
  "tmux"
  "nvim-config-sync"
  "wallpaperctl"
  "freerdp"
  "chromium"
] conference;
assert absent [
  "opencode"
  "claude-code"
  "mailspring"
  "mailspring-after-tray"
  "discord-canary"
  "slack"
  "1password"
  "obsidian"
  "handy"
  "sendspin"
  "obs-studio"
  "f3d"
  "wine-wow64"
  "ventoy"
  "Vial"
  "contextctl"
  "context-checkpoint"
  "quickshell-ai-usage"
  "zulu-ca-jdk"
  "direnv"
] conference;
assert builtins.all (
  name: !(builtins.hasAttr name conference.systemd.user.services)
) contextServices;
assert !(builtins.hasAttr "context-checkpoint" conference.systemd.user.timers);
assert conference.home.sessionVariables.SYNC_REPO_GROUPS == "core,desktop";
assert conference.programs.git.package.pname == "git";
assert !conference.programs.direnv.enable;
assert builtins.hasAttr "applications/webapp-supernote.desktop" conference.xdg.dataFile;
assert
  builtins.fromJSON conference.xdg.dataFile."quickshell/features.json".text == {
    contexts = false;
    personal = false;
    development = false;
  };
assert
  workstation.desktopContexts.enable && workstation.personalDesktop.enable && workstation.dev.enable;
assert withoutContexts.personalDesktop.enable && withoutContexts.dev.enable;
assert builtins.all (
  name: !(builtins.hasAttr name withoutContexts.systemd.user.services)
) contextServices;
assert !(builtins.fromJSON withoutContexts.xdg.dataFile."quickshell/features.json".text).contexts;
assert builtins.all (name: builtins.hasAttr name workstation.systemd.user.services) contextServices;
assert present [
  "contextctl"
  "context-checkpoint"
  "mailspring"
  "opencode"
  "claude-code"
] workstation;
assert absent [ "linux-wallpaperengine" ] conference;
assert absent [ "linux-wallpaperengine" ] workstation;
{
  conference = "PASS: meeting apps/core utilities retained; contexts/personal/development disabled";
  workstation = "PASS: existing desktop contexts and workstation packages retained";
  independent = "PASS: desktopContexts can be disabled on another host without disabling personal/development modules";
  wallpaper = "PASS: linux-wallpaperengine absent from both profiles";
}
