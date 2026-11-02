{ pkgs }:
pkgs.stdenvNoCC.mkDerivation {
  pname = "opencode-claude-auth-lazy";
  version = "2.2.1";
  src = pkgs.fetchzip {
    url = "https://registry.npmjs.org/opencode-claude-auth/-/opencode-claude-auth-2.2.1.tgz";
    hash = "sha256-qK4WL2yrgrmJ4RHZ8rDJlgvf5/rdb0AF5LYGIxpYxkA=";
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
    OPENCODE_AUTH_TEST_ROOT="$TMPDIR" CLAUDE_AUTH_PLUGIN="$PWD/opencode-claude-auth.js" \
      node --test "$TMPDIR/tests/test-claude-auth.mjs"
    runHook postCheck
  '';
  installPhase = ''
    mkdir -p "$out"
    cp -r dist opencode-claude-auth.js package.json LICENSE "$out/"
  '';
}
