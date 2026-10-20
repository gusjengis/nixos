# Coherent commit history result

## Outcome

Completed the explicitly authorized local commit-history phase on 2026-10-20.
The Neovim submodule was committed before its parent gitlink. Existing history,
unrelated working edits and all implementation sources were preserved. No pushes,
rebases, amendments, Git configuration changes, hook bypasses, rebuilds, live-session
migrations, reboots or fleet rollout were performed.

Prerequisites inspected: both implementation handoffs/results, repository
instructions, baseline heads/status and patch boundaries, implementation completion
marker, PTY repair evidence, workflow status and the passing four-command independent
gate under `/tmp/opencode/single-checkpoint-20261019/`. Earlier failed repair runs
remain historical evidence; the latest independent gate passed.

## Commit sequence

Neovim repository (`home/features/development/nvim/config`, branch `master`):

- `713690211f7f9ff541e6f22601084458e986b924`
  — `feat(persistence): save incremental editor recovery`
  Replaces project discovery with exact-directory recovery, binary-safe RAM RPC,
  immutable chunks and one current standalone directory checkpoint. Preserves legacy
  session files and original project files. Includes plugin lock/keymap migration.

Parent repository (`main`), after baseline
`eabaf732318a3400de4864a8c52c385fdaec0337`, in dependency order:

1. `892990c8b8d3468b46d79f1c81489b3e84de2e7f`
   — `feat(contexts): protect registered Git checkouts`
   Explicit registration, guarded clone/init, exact conservative exclusions and
   Syncthing sessions-share wiring, with repository/Git tests.
2. `b9f715dcbf044b8a8b910df5cbbb93de1ed2c71d`
   — `feat(persistence): add current checkpoint adapters`
   Current-root chunk store, native granular chat bundles, TUI route observation,
   Neovim gitlink/runtime-lock adjustment and store/chat/editor tests. Publication
   scratch exclusions were staged separately from the earlier sync foundation.
3. `290aa31a7610d12c0d22785c0dd1d1f6849c11f0`
   — `feat(tmux): checkpoint before native destruction`
   Asynchronous native barrier/package overlay and twelve native tests. Interception
   remains inactive until the following integration configures its helper.
4. `2c9c911f51e200cb462e5ab32c304e3c3dc4ca7d`
   — `feat(contexts): wire checkpointed desktop lifecycle`
   Catalog/notebooks, coordinator, placement, picker, managed close, periodic saves
   and early shutdown inhibition with their regression harnesses. Catalog and
   coordinator share lifecycle imports and are kept together as a runnable unit.
5. `e7ae17d21d5b8b45ab0e441267846481a0a61c1f`
   — `feat(contexts): add guarded repository relocation`
   Explicit dry-run/apply relocation and flatten tools, journals/rollback checks,
   dirty-data preservation tests and context-based development clone destinations.
6. `docs(contexts): record checkpoint history and verification`
   Current behavior, source handoffs, implementation evidence and this completion
   report. Its actual hash belongs in the machine-local result, avoiding a
   self-referential commit hash here.

Each staged diff was inspected before its normal commit. Tests travel with their
implementations. The initial parent branch was already three commits ahead of its
locally recorded `origin/main`; those commits were preserved.

## Verification performed in this phase

All commands below exited zero. Commands ran from `/etc/nixos` unless noted.
No production source was changed during history assembly.

- `PERSISTENCE_NATIVE_TESTS=1 /nix/store/iaadi6k26dcajhfvghqc2al1sf6v0iz4-python3-3.14.7-env/bin/python3 -B home/features/development/nvim/test_persistence.py -q`
  — 14 native editor tests passed, including the real 30-second timer.
- `python3 -B -m unittest test_repositories test_context_git -q`
  from `home/features/desktop/contexts` — 41 tests passed.
- `PERSISTENCE_NATIVE_TESTS=1 python3 -B -m unittest test_checkpoint_store test_chat_portability -q`
  from `home/features/desktop/contexts` — 17 store/chat tests passed.
- `PERSISTENCE_TMUX=/nix/store/npp3sp2cbnn46bvmn1byfkb7ldlsyfsl-tmux-3.7c/bin/tmux python3 -B home/features/terminal/tmux/test_checkpoint.py -q`
  — all 12 native barrier tests passed.
- Full context discovery ran through an owned PTY using
  `script -q -e -c "env PERSISTENCE_NATIVE_TESTS=1 PERSISTENCE_TMUX=/nix/store/npp3sp2cbnn46bvmn1byfkb7ldlsyfsl-tmux-3.7c/bin/tmux PERSISTENCE_RESURRECT=/nix/store/fy177g0k8bk83wpzrfzpy7kz0dfgwbb2-tmuxplugin-resurrect-unstable-2022-05-01/share/tmux-plugins/resurrect /nix/store/iaadi6k26dcajhfvghqc2al1sf6v0iz4-python3-3.14.7-env/bin/python3 -B -m unittest discover -s home/features/desktop/contexts -p 'test_*.py' -q" /dev/null`
  — 209 discovered, 207 passed, two intentional opt-in skips (real desktop fixture
  and live system-D-Bus inhibitor probe). Includes migration/flatten and native
  coordinator/editor, no-op/chunk, PTY RPC and failed-restore contracts.
- `XDG_RUNTIME_DIR=/tmp/opencode/single-checkpoint-20261019/lua-runtime HYPRLAND_INSTANCE_SIGNATURE=test-commits nvim --headless -u NONE -i NONE -n -l home/features/desktop/hyprland/config/sessions/test.lua`
  — compositor session aggregate passed.
- `nvim --headless -u NONE -i NONE -n -l home/features/desktop/hyprland/config/test_context_terminals.lua`
  — all 13 placement/lifecycle tests passed.
- `QT_QPA_PLATFORM=wayland WAYLAND_DISPLAY=/run/user/1000/wayland-1 XDG_RUNTIME_DIR=/tmp/opencode/single-checkpoint-20261019/lua-runtime HYPRLAND_INSTANCE_SIGNATURE=test-commits qs -p home/features/desktop/quickshell/test_session_picker.qml`
  — explicitly printed runtime/dispensary filtering and action-guard success;
  isolated signature/runtime, no windows displayed.
- `nix eval --json .#homeConfigurations --apply 'xs: builtins.mapAttrs (_: x: x.activationPackage.drvPath) xs'`
- `nix eval --json .#nixosConfigurations --apply 'xs: builtins.mapAttrs (_: x: x.config.system.build.toplevel.drvPath) xs'`
  — all nine Home Manager and nine NixOS configurations evaluated. Existing
  Nextcloud major-version advisory remained informational; no package changed.
- `ruff check home/features/desktop/contexts/checkpoint_store.py home/features/desktop/contexts/persistence.py home/features/desktop/contexts/chat_portability.py home/features/desktop/contexts/test_checkpoint_store.py`
  — scoped lint passed.
- Parent/submodule whitespace checks and each staged `git diff --cached --check`
  passed. Checked commit boundaries, remaining diffs and local submodule object;
  final marker is written only after confirming both staged indexes are empty and
  the parent gitlink equals the clean Neovim HEAD.

## Intentionally uncommitted paths

These pre-existing/runtime preferences remain writable and uncommitted:

- `home/features/agents/opencode/state/kv.json`: diff-viewer preference.
- `home/features/agents/opencode/state/model.json`: runtime model variant selection.
- `home/features/files/thunar/xfconf/thunar.xml`: file-manager view/sort/window state.
- `home/features/desktop/hyprland/config/variables.pc.lua`: PC Discord/Slack webapp
  launcher preferences unrelated to terminal checkpointing.
- `home/features/desktop/hyprland/config/workspaces.lua`: only the Slack scratchpad
  disable preference remains; checkpoint/notebook integration hunks were committed.

The Neovim working tree is clean. Machine-local workflow controllers, credentials,
logs, completion markers and staging helper patches remain outside Git in
`/tmp/opencode/single-checkpoint-20261019/`.

## Publication order and deferred deployment

No remote was updated. With separate publication authorization:

1. Push Neovim `master` to `https://github.com/gusjengis/nvim.git`, making
   `713690211f7f9ff541e6f22601084458e986b924` fetchable first.
2. Only after that succeeds, push the parent `main` history to
   `https://github.com/gusjengis/nixos.git`.
3. Other computers can then fetch the parent and initialize/update its Neovim
   submodule, preserving their own dirty checkouts before any update.

History readiness is not deployment. ARM package builds, a normal-profile canary
and any later fleet rollout remain separate work. Loose/non-tmux terminal support
and migration of running legacy sessions remain deferred. No old servers, editors
or chats were restarted by this phase.
