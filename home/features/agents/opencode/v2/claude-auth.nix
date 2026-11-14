{ pkgs }:
pkgs.stdenvNoCC.mkDerivation {
  pname = "opencode-v2-claude-auth-lazy";
  version = "3.0.0";
  src = pkgs.fetchzip {
    url = "https://registry.npmjs.org/opencode-claude-auth/-/opencode-claude-auth-3.0.0.tgz";
    hash = "sha256-18lx3a57VnLJHKbxKVrVVeNrOx0dbeWzbowTcBMU8WU=";
  };
  patches = [ ./claude-auth.patch ];
  dontBuild = true;
  nativeCheckInputs = [ pkgs.nodejs ];
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    mkdir -p "$TMPDIR/tests"
    cp ${./test-claude-auth.mjs} "$TMPDIR/tests/test-claude-auth.mjs"
    cp ${./claude-auth-fixture.mjs} "$TMPDIR/tests/claude-auth-fixture.mjs"
    CLAUDE_AUTH_V2_SOURCE="$PWD" node --test "$TMPDIR/tests/test-claude-auth.mjs"
    runHook postCheck
  '';
  installPhase = ''
    mkdir -p "$out"
    cp -r dist index.js package.json LICENSE "$out/"
  '';
}
