{
  description = "Isolated OpenCode 2 migration candidate";
  inputs.opencode.url = "github:anomalyco/opencode/dc2ffcf8bf26f9e669b6aa22b95f50e12be15e06";
  outputs = { opencode, ... }: {
    packages.x86_64-linux.default = import ./v2/package.nix { inherit opencode; };
    packages.x86_64-linux.claude-auth = import ./v2/claude-auth.nix {
      pkgs = opencode.inputs.nixpkgs.legacyPackages.x86_64-linux;
    };
    packages.x86_64-linux.sandbox-python = opencode.inputs.nixpkgs.legacyPackages.x86_64-linux.python3.withPackages
      (ps: [ ps.pyyaml ps.plyvel ]);
    packages.x86_64-linux.session-notify = import ./v2/session-notify.nix {
      pkgs = opencode.inputs.nixpkgs.legacyPackages.x86_64-linux;
    };
  };
}
