{
  config,
  pkgs,
  lib,
  ...
}:

let
  # Both nixpkgs's `aiosendspin` (6.0.5) and PyPI's latest released
  # `sendspin` (7.5.0, hard-pinned to `aiosendspin~=6.0.1`) predate a fix
  # upstream shipped days ago: Music Assistant's server/state messages now
  # include a "seek" entry in supported_commands that aiosendspin <9.1.1
  # doesn't recognize as a valid MediaCommand, so mashumaro rejects the
  # *entire* message and supported_commands never updates from empty.
  # Concretely: canPlay/canPause/canGoNext/canGoPrevious all read as
  # permanently false over MPRIS, so playback itself keeps working (it
  # doesn't depend on server/state) but every transport control -- buttons
  # here, media keys, playerctl -- silently no-ops.
  #
  # Fixed upstream in Sendspin-Protocol/sendspin#277 (bumped to
  # aiosendspin~=9.1.1) but not yet cut as a PyPI release, so this builds
  # `sendspin` straight from that commit instead of nixpkgs's frozen 7.5.0,
  # with `aiosendspin` overridden to match. Re-check for a new PyPI release
  # (or nixpkgs catching up) next time this is touched, and drop this
  # whole override in favor of plain `pkgs.python3Packages.sendspin` if so.
  python = pkgs.python3.override {
    packageOverrides = pySelf: pySuper: {
      # New dependency of aiosendspin>=7 (pairing/encryption); not yet in
      # nixpkgs.
      cpace = pySelf.buildPythonPackage {
        pname = "cpace";
        version = "0.1.0";
        format = "wheel";
        src = pkgs.fetchurl {
          url = "https://files.pythonhosted.org/packages/fa/e8/949c45844ad0d65d0112c2c4fa11cc8a7c4359fe2a20667e00c930860bef/cpace-0.1.0-py3-none-any.whl";
          hash = "sha256-n6u2CnEahZNCJb5AgbP1mU4cpM0TNcW5FxdwyPGi/aM=";
        };
        propagatedBuildInputs = [ pySelf.cryptography ];
        doCheck = false;
      };

      aiosendspin = pySuper.aiosendspin.overridePythonAttrs (old: {
        version = "9.1.1";
        src = pkgs.fetchFromGitHub {
          owner = "Sendspin";
          repo = "aiosendspin";
          rev = "9.1.1";
          hash = "sha256-ZWYUmiAhxzb/B4lRPuEe35tCeuO5tduZXCg6FpW8PlU=";
        };
        propagatedBuildInputs = (old.propagatedBuildInputs or [ ]) ++ [
          pySelf.cpace
          pySelf.noiseprotocol
          pySelf.cryptography
        ];
        # Test suite needs network/asyncio fixtures the sandbox doesn't
        # have; doesn't affect the built package.
        doCheck = false;
      });

      aiosendspin-mpris = pySuper.aiosendspin-mpris.overridePythonAttrs (old: {
        patches = (old.patches or [ ]) ++ [
          ./aiosendspin-mpris-artwork.patch
          ./aiosendspin-mpris-position.patch
          ./aiosendspin-mpris-threadsafe.patch
        ];
        doCheck = false;
      });

      sendspin = pySuper.sendspin.overridePythonAttrs (old: {
        # pyproject.toml carries a "version set by GH action on release"
        # 0.0.0 placeholder; nixpkgs's pyprojectVersionPatchHook rewrites it
        # to match this (PEP 440 dev-release syntax, since it isn't tagged).
        version = "7.5.0.dev20260917";
        src = pkgs.fetchFromGitHub {
          owner = "Sendspin-Protocol";
          repo = "sendspin";
          rev = "511645a9c685544250037f801b63bbc86b6e9000";
          hash = "sha256-60cuvSwnLYX+XwgBLvPm5agvnH+9gWNk5Bz/SabYzKQ=";
        };
        patches = (old.patches or [ ]) ++ [ ./sendspin-daemon-artwork.patch ];
        doCheck = false;
      });
    };
  };

  sendspinPkg = python.pkgs.toPythonApplication python.pkgs.sendspin;

  # t470 runs the Music Assistant server (system/hosts/t470/music_assistant.nix),
  # reachable over the tailnet. Sendspin's protocol port is separate from the
  # 8095 web UI port and is not discoverable over mDNS across Tailscale, so
  # this connects to it directly instead of relying on LAN discovery.
  massSendspinUrl = "ws://t470.tail29bd65.ts.net:8927/sendspin";
in
{
  config = lib.mkIf config.desktopEnv.enable {
    home.packages = [ sendspinPkg ];

    # Turns this machine into a real Sendspin playback target for Music
    # Assistant. Unlike the Chromium-wrapped MA web player, this registers a
    # proper, stable MPRIS player (aiosendspin-mpris, identity "Sendspin")
    # that does not unregister itself on pause, so the existing
    # playerctl-driven media keys keep controlling it without any custom
    # keybind changes.
    #
    # First connection to a new server needs manual pairing: watch
    # `journalctl --user -u sendspin -f` for the "Pairing required: enter
    # PIN ..." line, then approve it from the Music Assistant player setup
    # screen.
    systemd.user.services.sendspin = {
      Unit = {
        Description = "Sendspin audio player (Music Assistant playback target)";
        After = [ "network-online.target" ];
        Wants = [ "network-online.target" ];
      };
      Service = {
        Type = "simple";
        ExecStart = "${lib.getExe' sendspinPkg "sendspin"} daemon --url ${massSendspinUrl}";
        Restart = "on-failure";
        RestartSec = 5;
      };
      Install.WantedBy = [ "default.target" ];
    };
  };
}
