{ config, pkgs, inputs, repoRoot, legacy, sessionPolicy }:
let
  lib = pkgs.lib;
  root = "${repoRoot}/home/features/agents/opencode";
  system = pkgs.stdenv.hostPlatform.system;
  upstreamPkgs = inputs.opencode-v2.inputs.nixpkgs.legacyPackages.${system};
  native = import ./package.nix { opencode = inputs.opencode-v2; inherit system; };
  auth = import ./claude-auth.nix { pkgs = upstreamPkgs; };
  notify = import ./session-notify.nix { pkgs = upstreamPkgs; };
  policy = import ./policy-compat.nix { pkgs = upstreamPkgs; legacy = "${sessionPolicy}/guard.js"; };
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ps.plyvel ]);
  database = "${config.xdg.dataHome}/opencode-v2/opencode.db";
  environment = {
    OPENCODE_PROTOCOL = "2";
    OPENCODE_CONFIG_DIR = "${root}/v2/config";
    OPENCODE_DATA_DIR = "${config.xdg.dataHome}/opencode-v2";
    OPENCODE_STATE_DIR = "${root}/v2/state";
    OPENCODE_CACHE_DIR = "${config.xdg.cacheHome}/opencode-v2";
    OPENCODE_HANDOFF_FILE = "${config.xdg.stateHome}/desktop-contexts/opencode-profile.json";
    OPENCODE_V2_ROOT = "${root}/v2";
    OPENCODE_V2_AUTH = "${auth}";
    OPENCODE_V2_NOTIFY = "${notify}";
    OPENCODE_V2_POLICY = "${policy}";
    OPENCODE_V1_RULES = "${config.xdg.configHome}/opencode/AGENTS.md";
    OPENCODE_V1_SKILLS = "${config.xdg.configHome}/opencode/skills";
    OPENCODE_V1_BINARY = "${legacy.native}/bin/opencode";
    OPENCODE_V2_BINARY = "${native}/bin/opencode";
    OPENCODE_LEGACY_DATA_HOME = config.xdg.dataHome;
  };
  specification = {
    protocol = 2;
    inherit database environment;
    binary = "${native}/bin/opencode";
    legacy_binary = "${legacy.native}/bin/opencode";
    legacy_database = "${config.xdg.dataHome}/opencode/opencode.db";
    legacy_config = "${config.xdg.configHome}/opencode";
    contexts = "${repoRoot}/home/features/desktop/contexts";
    tmux = "${pkgs.tmux}/bin/tmux";
    state = "${root}/v2/state";
    legacy_state = "${root}/state";
    base_environment = {
      XDG_CONFIG_HOME = config.xdg.configHome;
      XDG_DATA_HOME = config.xdg.dataHome;
      XDG_STATE_HOME = config.xdg.stateHome;
      XDG_CACHE_HOME = config.xdg.cacheHome;
    };
  };
  specificationFile = pkgs.writeText "opencode-v2-profile.json" (builtins.toJSON specification);
  launcher = pkgs.writeShellApplication {
    name = "opencode";
    runtimeInputs = [ python pkgs.tmux ];
    text = ''exec python3 -B "${root}/v2/launch.py" ${specificationFile} "$@"'';
  };
  chats = pkgs.writeShellApplication {
    name = "opencode-context-chats";
    runtimeInputs = [ python ];
    text = ''exec python3 -B "${repoRoot}/home/features/desktop/contexts/context_chat_library.py" "$@"'';
  };
in
{ inherit native launcher chats python specificationFile; }
