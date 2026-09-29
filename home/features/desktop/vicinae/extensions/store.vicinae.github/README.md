Bundled from `vicinaehq/extensions` revision `def646b3655e13759d2b0a7b9d605f55fe83a5f7`, `extensions/github`.

Local changes: remove the required `personalAccessToken` preference from `package.json` and replace `src/api/githubClient.ts` with `githubClient.ts` alongside this file. Rebuild with `npm ci` and `npm run build -- --out /etc/nixos/home/features/desktop/vicinae/extensions/store.vicinae.github` from the upstream extension source. The bundle reads `~/.config/secrets/PAT` at runtime; never embed or copy the token into this repository or the Nix store.

Pull request view also has local changes to `src/pullRequests.tsx`, `src/config.ts`, `src/types.ts`, and `src/utils/getPullRequestFilterQuery.ts`: status labels and icons, plus merged/closed filters for PRs authored by you. Reapply these changes and the four `assets/pr_{draft,open,merged,closed}.svg` icons before rebuilding from a fresh upstream checkout.

Personal pull request source lives on `gusjengis/extensions` branch `personal/github-pr-inbox` (checked out at `~/Documents/Code/extensions`). It adds Inbox, Incoming, author names, and the shorter launcher title. The installed bundle was built from a temporary copy of that source with only the token-file override above; do not build the unmodified fork directly into this directory or it will restore the required token preference.
