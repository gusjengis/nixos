{
  config,
  lib,
  pkgs,
  ...
}:

{
  imports = [
    ./claude-code
    ./opencode
  ];

  # Python is broadly useful to coding agents for inspection and automation.
  home.packages = lib.optionals config.dev.enable [
    pkgs.python314
  ];
}
