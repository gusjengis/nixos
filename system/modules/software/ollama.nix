# Local inference host.
#
# One machine in the fleet keeps a small model resident on its GPU so other
# machines can ask it questions over the tailnet without touching a metered
# API. Today the only caller is the OpenCode auto-router's prompt classifier
# (see home/features/agents/opencode/auto-router/), which runs on every user
# turn and therefore has to be both free and fast.
#
# Exposure is deliberately tailnet-only: Ollama has no authentication of any
# kind, so the port is opened on the `tailscale0` interface rather than
# globally, and the daemon is never reachable from the LAN or the internet.
{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.ollama;
in
{
  options.ollama = {
    enable = lib.mkEnableOption "a tailnet-local Ollama inference server";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.ollama-cuda;
      defaultText = lib.literalExpression "pkgs.ollama-cuda";
      description = ''
        Build of Ollama to run. The GPU backend is chosen by the package rather
        than by an option: `ollama-cuda`, `ollama-rocm`, `ollama-vulkan`, or
        plain `ollama` for CPU, which is too slow to be worth serving.
      '';
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 11434;
      description = "Port the daemon listens on. Reachable over `tailscale0` only.";
    };

    models = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [ "qwen3:4b-instruct-2507-q8_0" ];
      description = ''
        Models pulled when the daemon starts. Pulls are idempotent, so listing a
        model that is already on disk costs nothing.
      '';
    };

    preload = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "qwen3:4b-instruct-2507-q8_0";
      description = ''
        Model held in VRAM indefinitely. Loading a 4-20 GB model off disk takes
        seconds, which is longer than the request that triggered it is allowed
        to take, so the classifier's model is loaded ahead of any caller and
        re-warmed periodically in case the daemon restarts.
      '';
    };

    contextLength = lib.mkOption {
      type = lib.types.int;
      default = 16384;
      description = ''
        Default context window. Ollama otherwise picks 4096 on a 24 GB card and
        silently truncates anything longer, which for a classifier means
        grading a prompt it only partly read.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    services.ollama = {
      enable = true;
      package = cfg.package;
      # Bound to every interface, but only reachable through the firewall rule
      # below. Binding to the Tailscale address directly would make the unit
      # depend on tailscaled having finished negotiating an address at boot.
      host = "0.0.0.0";
      port = cfg.port;
      openFirewall = false;
      loadModels = cfg.models;

      environmentVariables = {
        # Never unload on idle. This host exists to answer instantly.
        OLLAMA_KEEP_ALIVE = "-1";
        OLLAMA_FLASH_ATTENTION = "1";
        OLLAMA_CONTEXT_LENGTH = toString cfg.contextLength;
        # Each parallel slot reserves its own KV cache, multiplying VRAM by the
        # slot count. One caller at a time, with the full window, is the right
        # trade for a classifier.
        OLLAMA_NUM_PARALLEL = "1";
        OLLAMA_MAX_LOADED_MODELS = "2";
      };
    };

    networking.firewall.interfaces."tailscale0".allowedTCPPorts = [ cfg.port ];

    environment.systemPackages = [ config.services.ollama.package ];

    # `keep_alive: -1` only applies from the moment a model is first loaded, so
    # something has to load it. The timer repeats because a daemon restart or a
    # manual `ollama stop` would otherwise leave the next caller paying the cold
    # load, and that caller is on a latency budget measured in milliseconds.
    systemd.services.ollama-preload = lib.mkIf (cfg.preload != null) {
      description = "Hold ${cfg.preload} resident in VRAM";
      after = [ "ollama.service" ];
      wants = [ "ollama.service" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        Type = "oneshot";
        Restart = "on-failure";
        RestartSec = 30;
      };
      script = ''
        url="http://127.0.0.1:${toString cfg.port}"

        # Two separate waits. The daemon answers /api/tags long before
        # `loadModels` has finished pulling, so reaching the socket is not the
        # same as the model existing, and asking for a model that is still
        # downloading is a 404 rather than a queue. A first boot pulling 20 GB
        # over a domestic connection is the case this has to survive.
        for _ in $(${pkgs.coreutils}/bin/seq 1 360); do
          if ${pkgs.curl}/bin/curl -fsS --max-time 5 "$url/api/tags" \
            | ${pkgs.jq}/bin/jq -e --arg m ${lib.escapeShellArg cfg.preload} \
              'any(.models[]?; .name == $m or .model == $m)' >/dev/null 2>&1; then
            # An empty message list is Ollama's documented way to load a model
            # without generating anything.
            exec ${pkgs.curl}/bin/curl -fsS --max-time 900 "$url/api/chat" \
              -d ${
                lib.escapeShellArg (builtins.toJSON {
                  model = cfg.preload;
                  messages = [ ];
                  keep_alive = -1;
                })
              } >/dev/null
          fi
          sleep 10
        done

        echo "ollama-preload: ${cfg.preload} never appeared in /api/tags" >&2
        exit 1
      '';
    };

    systemd.timers.ollama-preload = lib.mkIf (cfg.preload != null) {
      description = "Re-warm ${cfg.preload} if it ever falls out of VRAM";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "2min";
        OnUnitActiveSec = "15min";
      };
    };
  };
}
