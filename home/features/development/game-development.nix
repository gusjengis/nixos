{
  config,
  lib,
  ...
}:

{
  options.gameDev.enable = lib.mkEnableOption "game development tools" // {
    default = false;
  };

  config = lib.mkIf (config.gameDev.enable && config.desktopEnv.enable) {
    # Reserved for tools that belong specifically to game development. Current
    # candidates remain disabled: VS Code, Unity, Blender, Plastic SCM, .NET,
    # Roslyn, and CUDA.
    home.packages = [ ];
  };
}
