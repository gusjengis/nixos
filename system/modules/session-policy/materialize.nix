{ pkgs }:
pkgs.runCommand "session-policy-material"
  {
    nativeBuildInputs = [
      pkgs.openssl
      pkgs.gnutar
      pkgs.gzip
      pkgs.python3
      pkgs.nodejs
    ];
  }
  ''
    mkdir -p "$out"
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -a \
      -pass file:${./material.seed} -in ${./material.enc} \
      | tar -xz -C "$out"
    export PYTHONDONTWRITEBYTECODE=1
    export TZDIR=${pkgs.tzdata}/share/zoneinfo
    python3 "$out/test_runtime.py"
    node "$out/test_guard.mjs"
  ''
