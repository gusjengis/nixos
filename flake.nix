{
  description = "System Flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    stable-nixpkgs.url = "nixpkgs/nixos-25.11";
  };

  outputs =
    {
      self,
      nixpkgs,
      stable-nixpkgs,
      ...
    }@inputs:
    let
      lib = nixpkgs.lib;
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      pkgsStable = import stable-nixpkgs { inherit system; };
    in
    {
      nixosConfigurations = {
        nixos = lib.nixosSystem {
          inherit system;
          specialArgs = {
            inherit inputs;
            stable = pkgsStable;
          };
          modules = [
            ./hardware-configuration.nix
            ./configuration.nix
            /etc/nix-modules/nixosModules
          ];
        };
      };
    };
}
