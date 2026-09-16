{
  config,
  pkgs,
  repoRoot,
  ...
}:
let
  configRoot = "${repoRoot}/home/features/git";

  # Path only. The token is read at runtime by shell code, never by Nix:
  # anything Nix reads is copied into the world-readable /nix/store.
  patFile = "${config.home.homeDirectory}/.config/secrets/PAT";
in
{
  home.packages = with pkgs; [
    gh
    lazygit
  ];

  programs.git = {
    enable = true;
    lfs.enable = true;
    settings = {
      user = {
        name = "gusjengis";
        email = "anthony.j.green@outlook.com";
      };

      # gh serves credentials from GH_TOKEN, so git never prompts and no
      # plaintext copy is written to ~/.git-credentials.
      credential."https://github.com".helper = "!gh auth git-credential";
      credential."https://gist.github.com".helper = "!gh auth git-credential";
      submodule.recurse = true;
    };
  };

  # gh treats GH_TOKEN as an already-authenticated session, so `gh auth login`
  # is never needed on a new machine once the secrets directory is present.
  programs.bash.initExtra = ''
    if [ -r "${patFile}" ]; then
      GH_TOKEN="$(< "${patFile}")"
      export GH_TOKEN
    fi
  '';

  xdg.configFile."lazygit/config.yml" = {
    force = true;
    source = config.lib.file.mkOutOfStoreSymlink "${configRoot}/lazygit.yml";
  };
}
