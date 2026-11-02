{ pkgs }:
# Executable plugin patch is immutable/rebuild-controlled; keep the upstream
# notification submodule untouched. Other editable integration files stay linked.
pkgs.runCommand "opencode-session-notify-bounded" { nativeBuildInputs = [ pkgs.patch ]; } ''
  mkdir -p "$out"
  cp ${./session-notify/session-notify.js} "$out/session-notify.js"
  chmod u+w "$out/session-notify.js"
  patch --directory="$out" --strip=1 < ${./session-notify-timeout.patch}
''
