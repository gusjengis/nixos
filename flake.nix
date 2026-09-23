{
  description = "Home Manager Flake";

  inputs = {
    nixpkgs.url = "nixpkgs/nixpkgs-unstable";
    # Keep system and Home Manager package sets independent during migration.
    nixpkgs-system.url = "github:NixOS/nixpkgs/nixos-unstable";
    disko = {
      url = "github:nix-community/disko";
      inputs.nixpkgs.follows = "nixpkgs-system";
    };
    apple-silicon.url = "github:nix-community/nixos-apple-silicon";
    home-manager.url = "github:nix-community/home-manager";
    home-manager.inputs.nixpkgs.follows = "nixpkgs";
    alga.url = "github:Tenzer/alga";
    nix-flatpak.url = "github:gmodena/nix-flatpak";
    rmatrix.url = "github:RoastBeefer00/rmatrix";
    claude-code-nix = {
      url = "github:sadjow/claude-code-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    # Hyprland, built from a personal fork rather than nixpkgs.
    #
    # Tracks a branch, so `nix flake update hyprland && rehome` moves every
    # machine to whatever that branch points at now. To go back to upstream,
    # change this URL to github:hyprwm/Hyprland/main for the dev channel or to
    # a tag like github:hyprwm/Hyprland/v0.57.0 for a release.
    #
    # Its nixpkgs is deliberately NOT made to follow ours. Hyprland pins the
    # nixpkgs it is tested against, and overriding that is the usual cause of
    # compile failures when nixpkgs-unstable drifts.
    hyprland = {
      url = "github:gusjengis/Hyprland/personal";
    };
    hyprpicker.url = "github:gusjengis/hyprpicker/feature/format-cycling";
    # Caveman skill suite for OpenCode (output-token compression).
    # Update to latest: nix flake update caveman && rehome
    caveman = {
      url = "github:JuliusBrussee/caveman";
      flake = false;
    };
    # OpenCode pinned upstream, ahead of the nixpkgs package.
    # Bump by editing the tag below, then: nix flake update opencode && rehome
    opencode = {
      url = "github:anomalyco/opencode/v1.18.29";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      nixpkgs,
      nixpkgs-system,
      home-manager,
      ...
    }@inputs:
    let
      lib = nixpkgs.lib;
      repoRoot = "/etc/nixos";

      # Every machine this configuration is deployed to. Generated management
      # commands retain their roster key so runtime hostname drift is harmless.
      hosts = import ./system/hosts;

      systemHosts = lib.filterAttrs (_: host: host.systemManaged or true) hosts;

      pkgsFor =
        system:
        import nixpkgs {
          inherit system;
          overlays = [
            # Make the flake inputs reachable from any module through `pkgs`.
            (final: prev: { inputs = inputs; })
          ];
          config.allowUnfree = true;
        };

      homeConfigurationFor =
        hostName: host:
        home-manager.lib.homeManagerConfiguration {
          pkgs = pkgsFor host.system;
          extraSpecialArgs = {
            inherit
              inputs
              hosts
              hostName
              repoRoot
              ;
          };
          modules = [
            inputs.nix-flatpak.homeManagerModules.nix-flatpak
            ./home
          ];
        };

      systems = lib.unique (lib.mapAttrsToList (_: host: host.system) hosts);

      # Editor tooling for this repository. Neovim reads it through direnv
      # (.envrc), so language servers and formatters come from the flake that
      # owns the project instead of from a global, unpinned install.
      devShellFor =
        system:
        let
          pkgs = pkgsFor system;
        in
        pkgs.mkShell {
          packages = with pkgs; [
            nil # Nix
            nixfmt
            lua-language-server # Neovim config, Hyprland config
            stylua
            qt6.qtdeclarative # qmlls, for quickshell
            python3
            ruff # quickshell helper scripts
            bash-language-server
            shellcheck
          ];
        };

      nixosConfigurationFor =
        hostName: host:
        let
          hostDir = ./system/hosts + "/${hostName}";

          # Machines installed by `nix run .#install` have no generated
          # hardware-configuration.nix: Disko owns their `fileSystems` and
          # Facter supplies their kernel and initrd modules. The machines that
          # predate the installer keep theirs, so this import stays optional
          # rather than becoming required of new hosts.
          generatedHardware = hostDir + "/hardware-configuration.nix";
        in
        nixpkgs-system.lib.nixosSystem {
          system = host.system;
          specialArgs = {
            inherit inputs hosts hostName;
            system = host.system;
          };
          modules = [
            inputs.disko.nixosModules.disko
            {
              hardware.facter.reportPath = hostDir + "/facter.json";
            }
            (hostDir + "/disk.nix")
          ]
          ++ lib.optional (builtins.pathExists generatedHardware) generatedHardware
          ++ [
            (hostDir + "/configuration.nix")
            ./system/modules
          ];
        };

      # The installer's question list. See system/install/catalog.nix: this is
      # derived from the evaluated option trees, so it cannot describe a module
      # that no longer exists.
      catalog = import ./system/install/catalog.nix {
        inherit lib;
        sourceRoot = ./.;
        roles = import ./system/install/roles.nix;
      };

      roleCatalogFor =
        hostName: host:
        catalog.forHost {
          inherit hostName;
          meta = host;
          nixosOptions =
            if systemHosts ? ${hostName} then self.nixosConfigurations.${hostName}.options else { };
          homeOptions = self.homeConfigurations.${hostName}.options;
        };

      installerFor =
        system:
        (pkgsFor system).callPackage ./system/install/package.nix {
          repoUrl = "https://github.com/gusjengis/nixos.git";
        };

      self = {
        homeConfigurations = lib.mapAttrs homeConfigurationFor hosts;
        nixosConfigurations = lib.mapAttrs nixosConfigurationFor systemHosts;

        roleCatalogs = lib.mapAttrs roleCatalogFor hosts;

        # Facts the installer needs before any host configuration exists.
        installer = {
          # What a machine installed today should pin `system.stateVersion` to.
          # Read from the system nixpkgs rather than hardcoded, so it cannot go
          # stale the way a literal in a template would.
          stateVersion = nixpkgs-system.lib.trivial.release;
        };

        packages = lib.genAttrs systems (system: {
          install = installerFor system;
        });

        apps = lib.genAttrs systems (system: {
          install = {
            type = "app";
            program = lib.getExe (installerFor system);
            meta.description = "Install this configuration onto this machine";
          };
          default = self.apps.${system}.install;
        });

        devShells = lib.genAttrs systems (system: {
          default = devShellFor system;
        });

        checks = lib.genAttrs systems (
          system:
          let
            pkgs = pkgsFor system;

            hostsFor = lib.filterAttrs (_: host: host.system == system) hosts;
          in
          {
            # Builds the installer, which also runs its tests.
            installer = installerFor system;

            installer-lint = pkgs.runCommand "installer-lint" { nativeBuildInputs = [ pkgs.ruff ]; } ''
              cd ${./system/install/installer}
              ruff check --no-cache .
              ruff format --no-cache --check .
              touch $out
            '';

            # Evaluating every host's catalog is what enforces the consistency
            # assertions in system/install/catalog.nix, so `nix flake check`
            # catches metadata that names a module which has been renamed away.
            role-catalogs = pkgs.writeTextFile {
              name = "role-catalogs";
              text = builtins.toJSON (lib.mapAttrs (name: _: self.roleCatalogs.${name}) hostsFor);
            };
          }
        );
      };
    in
    self;
}
