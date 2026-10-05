# Local inference host.
#
# One machine in the fleet keeps a small model resident on its GPU so other
# machines can ask it questions over the tailnet without touching a metered
# API. The most demanding caller is the OpenCode auto-router's prompt
# classifier (see home/features/agents/opencode/auto-router/), which runs on
# every user turn and therefore has to be both free and fast; the note pipeline
# on omega (system/hosts/omega/notes.nix) uses the same models and embedders.
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
      example = [ "qwen3.8:27b" ];
      description = ''
        Models pulled when the daemon starts. Pulls are idempotent, so listing a
        model that is already on disk costs nothing.
      '';
    };

    preload = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "qwen3.8:27b";
      description = ''
        Model held in VRAM indefinitely. Loading a 4-20 GB model off disk takes
        seconds, which is longer than the request that triggered it is allowed
        to take, so the classifier's model is loaded ahead of any caller and
        re-warmed periodically in case the daemon restarts.
      '';
    };

    embedders = lib.mkOption {
      type = lib.types.attrsOf (
        lib.types.submodule {
          options = {
            from = lib.mkOption {
              type = lib.types.str;
              example = "hf.co/jinaai/jina-embeddings-v5-text-small-retrieval-GGUF:Q8_0";
              description = "Model to pull and build on (`FROM` in the Modelfile).";
            };
            contextLength = lib.mkOption {
              type = lib.types.int;
              default = 4096;
              description = ''
                Longest single input. Embedding context is per text, not per
                corpus, so this only has to fit one note or query; every token
                of it costs KV cache whether used or not.
              '';
            };
            cpu = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = "Keep every layer off the GPU (`num_gpu 0`).";
            };
          };
        }
      );
      default = { };
      description = ''
        Embedding models, built under the attribute name from a pinned upstream
        model with their own context, and held resident like `preload`.
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
        # Every resident model, plus one slot so an ad-hoc model is not loaded
        # by evicting a resident one (it still has to fit in VRAM).
        OLLAMA_MAX_LOADED_MODELS = toString (
          lib.length (lib.attrNames cfg.embedders) + (if cfg.preload != null then 1 else 0) + 1
        );
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
      # Also pulled in by ollama.service itself, so a daemon restart - which a
      # `rebuild` performs - re-warms immediately instead of leaving the model
      # cold until the next timer tick.
      wantedBy = [
        "multi-user.target"
        "ollama.service"
      ];
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
            # Deliberately a real generation rather than the empty-message form
            # that merely loads the weights. Loading is not warming: the first
            # request to actually decode a token pays for the compute graph and
            # the sampler on top, which measured at three seconds against two
            # hundred milliseconds once warm. A caller on a sub-second budget
            # treats that as a failure and falls back, so the warm-up has to
            # happen here and not on somebody's prompt.
            exec ${pkgs.curl}/bin/curl -fsS --max-time 900 "$url/api/chat" \
              -H 'content-type: application/json' \
              -d ${
                lib.escapeShellArg (builtins.toJSON {
                  model = cfg.preload;
                  stream = false;
                  keep_alive = -1;
                  messages = [
                    {
                      role = "user";
                      content = "warmup";
                    }
                  ];
                  options = {
                    temperature = 0;
                    num_predict = 1;
                  };
                })
              } >/dev/null
          fi
          sleep 10
        done

        echo "ollama-preload: ${cfg.preload} never appeared in /api/tags" >&2
        exit 1
      '';
    };

    # Builds each embedder from its pinned upstream model with its own
    # parameters, then loads it for good. Rerun on a timer for the same reason
    # as ollama-preload: a daemon restart empties memory.
    systemd.services.ollama-embedders = lib.mkIf (cfg.embedders != { }) {
      description = "Build and hold Ollama embedding models resident";
      after = [
        "ollama.service"
        "ollama-preload.service"
      ];
      wants = [ "ollama.service" ];
      wantedBy = [
        "multi-user.target"
        "ollama.service"
      ];
      path = [
        config.services.ollama.package
        pkgs.curl
      ];
      environment = {
        OLLAMA_HOST = "127.0.0.1:${toString cfg.port}";
        # `ollama create` keeps state in the daemon, but the CLI wants a home.
        HOME = "/run/ollama-embedders";
      };
      serviceConfig = {
        Type = "oneshot";
        RuntimeDirectory = "ollama-embedders";
        Restart = "on-failure";
        RestartSec = 30;
      };
      script =
        ''
          for _ in $(seq 1 360); do
            curl -fsS --max-time 5 "http://$OLLAMA_HOST/api/tags" >/dev/null 2>&1 && break
            sleep 10
          done
        ''
        + lib.concatStrings (
          lib.mapAttrsToList (
            name: embedder:
            let
              modelfile = pkgs.writeText "${name}.Modelfile" ''
                FROM ${embedder.from}
                PARAMETER num_ctx ${toString embedder.contextLength}
                # Embedding mode sizes its compute buffer by the batch, which
                # Ollama otherwise sets to 2048: 1.2 GiB of VRAM for a 0.6B model.
                PARAMETER num_batch 512
                ${lib.optionalString embedder.cpu "PARAMETER num_gpu 0"}
              '';
            in
            ''
              # Pull only once, so a re-warm never depends on the internet.
              ollama show ${lib.escapeShellArg embedder.from} >/dev/null 2>&1 \
                || ollama pull ${lib.escapeShellArg embedder.from}
              ollama create ${lib.escapeShellArg name} -f ${modelfile}
              curl -fsS --max-time 600 "http://$OLLAMA_HOST/api/embed" \
                -H 'content-type: application/json' \
                -d ${
                  lib.escapeShellArg (builtins.toJSON {
                    model = name;
                    input = "warmup";
                    keep_alive = -1;
                  })
                } >/dev/null
            ''
          ) cfg.embedders
        );
    };

    systemd.timers.ollama-embedders = lib.mkIf (cfg.embedders != { }) {
      description = "Re-warm Ollama embedding models";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "3min";
        OnUnitActiveSec = "15min";
      };
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
