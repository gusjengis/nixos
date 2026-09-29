Bundled from `vicinaehq/extensions` revision `def646b3655e13759d2b0a7b9d605f55fe83a5f7`, `extensions/github`.

Local changes: remove the required `personalAccessToken` preference from `package.json` and replace `src/api/githubClient.ts` with `githubClient.ts` alongside this file. Rebuild with `npm ci` and `npm run build -- --out /etc/nixos/home/features/desktop/vicinae/extensions/store.vicinae.github` from the upstream extension source. The bundle reads `~/.config/secrets/PAT` at runtime; never embed or copy the token into this repository or the Nix store.
