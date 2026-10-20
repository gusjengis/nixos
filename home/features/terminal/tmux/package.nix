{ pkgs }:
pkgs.tmux.overrideAttrs (old: {
  patches = (old.patches or [ ]) ++ [ ./checkpoint.patch ];
  # User options are normally absent until set; register this one so native
  # interception can safely query it even with -f /dev/null.
  postPatch = (old.postPatch or "") + ''
    substituteInPlace cmd-queue.c --replace-fail \
      'command = options_get_string(global_options, "@persistence-checkpoint");' \
      'command = options_get(global_options, "@persistence-checkpoint") == NULL ? "" : options_get_string(global_options, "@persistence-checkpoint");'
  '';
})
