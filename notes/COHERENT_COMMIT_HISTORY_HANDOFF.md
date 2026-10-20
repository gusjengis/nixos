# Handoff: coherent commits after single-checkpoint implementation

## Authorization and prerequisite

Latest user request explicitly authorizes a second OpenCode session to create a
coherent, staged commit history so changes can be synced across computers. This
session is that commit-history phase. Earlier "do not commit" restrictions applied
to implementation; this explicit phase authorizes commits.

Start only after the implementation session finishes successfully and supervisor's
independent checks pass. Read `notes/SINGLE_CHECKPOINT_IMPLEMENTATION_HANDOFF.md`,
`notes/SINGLE_CHECKPOINT_IMPLEMENTATION_RESULT.md`, repository instructions and the
machine-local workflow status/baselines supplied in the initial prompt.

Do not push, force-push, amend, rebase existing published history, change Git config,
skip hooks, or create PRs. User requested commit history, not remote publication.
Report the submodule-first publication steps needed before other computers can
fetch new parent pointers. Preserve all working data, including unrelated edits.

## Inspect before staging

For parent and Neovim submodule, inspect `git status`, complete intended diffs,
`git log --oneline -10`, branch/remotes/tracking, and any applicable instructions.
There is substantial pre-existing uncommitted context work; it is not all authored
by the single-checkpoint worker. Supervisor saved initial diffs/status for reference.

Current baseline groups to investigate, not a blanket staging allowlist:

- Existing context catalog/notebooks, repository registration/clone exclusions,
  repository migrations, vault-sync and picker/runtime UI changes.
- Terminal persistence coordinator, editor/chat adapters, native tmux barrier,
  placement/close/shutdown wiring and tests.
- New single-checkpoint storage implementation and its tests/migration/docs.
- Neovim configuration is a separate Git submodule with dirty Lua configuration,
  plugin lock/keymap changes and new recovery adapter.
- Volatile `home/features/agents/opencode/state/kv.json` and unrelated application
  settings (for example Thunar XML) may be runtime/user state. Do not casually
  include them in a feature commit or reset/delete them. Leave unrelated changes
  uncommitted and identify them if intent cannot be established.
- Notes/handoffs can contain test paths and old status. Include useful source docs,
  exclude machine-local workflow credentials/logs, and review for secrets.

## Build coherent history

1. Identify dependency boundaries and briefly explain planned commits in session
   commentary. Separate earlier context foundation from terminal-specific changes
   where practical; use careful hunk staging when a file combines both.
2. Commit Neovim changes in the submodule before parent references that commit.
   Do not publish a parent pointer that refers to absent local content. Since push
   is not authorized, explicitly report that submodule commit must be pushed before
   distributing the parent commit; never pretend the remote already has it.
3. Create reviewable parent commits for runnable, dependency-ordered units. A
   reasonable structure is context/repository foundation, checkpoint storage and
   adapters, terminal/native/lifecycle integration, and final docs/tests. Use actual
   dependencies rather than mechanically forcing this outline. Tests should travel
   with their implementation where possible.
4. Keep each staged change focused and internally consistent; don't stage the
   entire dirty tree. Preserve existing commits and all unrelated working edits.
5. Inspect each staged diff before committing. Follow repository commit style;
   normal concise Conventional Commit prose is appropriate. Run relevant checks.
6. If a hook/commit fails, fix the actual issue and create a new commit normally;
   do not bypass hooks or amend a failed attempt. Report blockers rather than
   silently dropping files or making unrelated implementation changes.

Do not introduce standalone/non-tmux terminal support: user explicitly deferred it.
Do not migrate running legacy sessions, reboot PC, overwrite remote dirty trees, or
automatically roll out to the fleet. Changes needing more implementation/review
should be reported rather than disguised as history cleanup.

## Finish

Verify status, new commit sequence/diffs, submodule pointer, staged-index cleanliness
and the implementation's focused checks. A nonempty working tree is acceptable for
identified unrelated user/runtime changes; do not erase it merely to get clean status.

Write `notes/COMMIT_HISTORY_RESULT.md` before the final appropriate docs commit,
listing parent/submodule commit subjects, verification, intentionally uncommitted
paths, and publication order. Avoid listing a commit's own not-yet-known hash in its
contents; final session response and machine-local result may record exact hashes.

Initial prompt supplies a machine-local completion JSON path. Atomically write:

```json
{"status":"complete","scope":"coherent-commit-history",
 "parent_commits":["actual hashes"],"submodule_commits":["actual hashes"],
 "uncommitted_paths":["explained paths"],"pushed":false}
```

Use `status: "blocked"` and `reasons` for genuine blockers. Final response reports
actual commits, remaining changes, checks and required publication steps.
