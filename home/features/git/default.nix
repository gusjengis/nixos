{
  config,
  pkgs,
  repoRoot,
  ...
}:
let
  configRoot = "${repoRoot}/home/features/git";
  contextDir = "${repoRoot}/home/features/desktop/contexts";
  contextGit = pkgs.symlinkJoin {
    name = "git-context-aware";
    paths = [ pkgs.git ];
    nativeBuildInputs = [ pkgs.makeWrapper ];
    meta = pkgs.git.meta;
    postBuild = ''
      rm "$out/bin/git"
      makeWrapper ${pkgs.python3}/bin/python3 "$out/bin/git" \
        --add-flags "-B ${contextDir}/context-git.py" \
        --set CONTEXT_REAL_GIT "${pkgs.git}/bin/git"
    '';
  };

  # Path only. The token is read at runtime by shell code, never by Nix:
  # anything Nix reads is copied into the world-readable /nix/store.
  patFile = "${config.home.homeDirectory}/.config/secrets/api_keys/github-pat";
in
{
  home.packages = with pkgs; [
    gh
    lazygit
  ];

  programs.git = {
    enable = true;
    package = contextGit;
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
