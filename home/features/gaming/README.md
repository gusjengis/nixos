# Steam game launches

Enabling `gaming.enable` on a desktop installs a `steam` command through Home
Manager. It adds `-silent` to game-launch requests before calling the pinned
Nixpkgs Steam package. Existing and newly generated desktop shortcuts therefore
inherit the policy without rewriting Steam-owned files.

Supported launch forms: `steam://rungameid/...`, `steam://run/...`,
`steam://launch/...`, and `-applaunch`. Arguments remain intact and an existing
`-silent` is not duplicated. Starting `steam` without a game request, or opening
its library/store URLs, retains normal client UI behavior.

Apply on another machine by enabling `gaming.enable` and running `rehome`.
NixOS hosts still need `programs.steam.enable = true` for system integration.
