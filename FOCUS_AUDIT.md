# Focus & Cognitive Fluency Audit

Analysis of the current desktop/system setup through the lens of attention,
cognitive load, and sustained deep work. Written from a full repo survey
(Hyprland config, QuickShell, nvim, tmux, browser, autostart, notifications).

## TL;DR

The system already does a lot right — more than most setups. The gaps aren't
"add more blockers," they're **state visibility across sessions**. You have
zero persistent record of "what was I doing and why" that survives a context
switch, a reboot, or a day. That's the actual hole, and it matches your
instinct about wanting a scratchpad/quest-log.

---

## What's already working well (keep these)

- **Notifications as action list, not log** — the `session-notify` plugin
  design principle (only alert on things needing response, suppress when
  pane already focused) is exactly right and rare. Don't regress this.
- **Popup cap of 3, urgency-aware timeouts** on the QuickShell notification
  server — restrained vs. typical desktop notification stacks.
- **On-demand app launch via scratchpad workspaces** — Slack/Discord/GPT
  don't autostart, they open on first toggle. Good: no ambient pull from
  apps you didn't ask for yet.
- **BlockSite + Unhook + YouTube declutter extensions** — you've already
  identified and defused the single worst focus-destroyer (YouTube's
  recommendation/shorts surfaces).
- **Bedtime lockout** — a hard curfew beats a soft one. Soft blockers get
  negotiated with at 11pm; cgroup freezes don't.
- **zen-mode.nvim** — distraction-free editing already exists at the editor
  layer, which is where the actual work happens.
- **github-dark consistently across kitty/tmux/(likely)nvim** — low
  context-switch cost when eyes move between terminal panes; color scheme
  doesn't retrain your visual parser at each boundary.

---

## Friction points and psychology-relevant issues

### 1. Mailspring autostarts unconditionally, backgrounded
`autostart.lua` — every other comms app (Discord, Slack) is lazy/on-demand,
but email launches on every login regardless of intent. Email is the
highest-recall-cost interrupt category (each glance pulls in an unbounded
task list, not a single ping). Making it opt-in like Discord/Slack removes
the one channel that's currently ambient by default.

**Fix**: drop `mailspring --background` from autostart; let `SUPER+E`-style
scratchpad-toggle (mirroring the existing `email` special workspace) be the
only entry point, same as Slack/Discord already work.

### 2. `cord.lua` — Discord Rich Presence from Neovim
Broadcasting live coding status to Discord is a *social* signal generator:
it invites others to DM/interrupt you based on what you're doing right now,
and it's a subtle self-surveillance loop (you become aware of being
observed while coding). This cuts against every other anti-distraction
decision in the config.

**Fix**: consider disabling, or scope it to only fire outside declared focus
hours (see bedtime-lockout pattern — you already have the infrastructure to
gate behavior by time-of-day).

### 3. No persistent task/context memory — the actual gap
This is the one you already sensed. Concretely, right now:
- Obsidian vault exists but isn't wired into any workflow automation.
- `todo-comments.nvim` only surfaces TODOs *while inside a file* — no
  aggregation, no priority, no due dates, nothing that persists outside
  the editor.
- `linked_todos.lua` — you already tried to build exactly this and
  abandoned it (fully commented out). Worth revisiting *why* it didn't
  stick before building another version.
- tmux/nvim project switchers (harpoon2, neovim-project, QuickShell
  `projects.json`) solve "get me back to project X" but not "what was I
  doing in project X, and why."

The psychological cost: every context switch (interrupt, break, end of day,
next morning) pays a **reconstruction tax** — you have to reload state from
memory or from re-reading code/diffs, because nothing captured "next step"
or "why" at the moment you stopped. This is the single highest-leverage
thing to fix; it compounds daily.

### 4. Numbered workspaces + 13 named scratchpads = two competing mental models
`SUPER+0-9` (spatial/numeric) and `SUPER+<letter>` (mnemonic/named) are
different retrieval strategies running side by side. Numbered workspaces
ask "which slot did I put this in" (positional memory); named scratchpads
ask "what's the app's name" (semantic memory). Neither is wrong alone, but
maintaining both means every "get to X" decision requires picking a
retrieval strategy first — that's a tiny but constant tax, thousands of
times a day.

**Not urgent to fix**, since scratchpads dominate real usage (13 of them,
purpose-built), but worth noting: the numbered workspaces may be legacy
weight. If they're mostly unused, killing them simplifies the mental model
to one system.

### 5. QuickShell bar: translucent (0.6 opacity), wallpaper-adaptive palette
Already flagged internally in `BRAINSTORM.md`. Wallpaper-adaptive color +
low opacity means the bar's contrast/legibility is non-deterministic —
some wallpapers will make status icons harder to parse at a glance, which
matters for glanceable info (battery, notifications) that's supposed to be
processed *without* conscious attention. Glanceable UI should have
guaranteed contrast, full stop, independent of art choice.

**Fix**: keep wallpaper-adaptive *hue* if desired for aesthetics, but pin a
minimum contrast ratio / raise baseline opacity for text and icons
specifically (not the whole bar).

### 6. No time-tracking / no pomodoro / no session-length signal
There's real infrastructure for *presence* awareness (usage.py in
QuickShell, battery history logger) but nothing tracking **how long you've
been heads-down** or **how long since a break**. For sustained deep work,
the risk isn't distraction mid-session — your setup already suppresses
that well — it's the opposite failure mode: no natural stopping cue, which
leads to fatigue-driven attention decay that doesn't feel like "distracted"
so it goes unnoticed.

This doesn't need to be a nagging pomodoro popup (which itself is an
interrupt). Options ranging from passive to active:
- Passive: a QuickShell bar segment showing "time in current focus
  session" (you already compute uptime-like stats for other widgets).
- Semi-passive: ActivityWatch (local, no telemetry, categorizes window
  focus time) feeding a QuickShell widget — visibility without alarms.
- Active only if requested: a single, dismissible, low-urgency notification
  after N minutes continuous focus, using the *existing* notification
  urgency/timeout system so it doesn't fight your "action list not log"
  principle.

### 7. Font mixing in QuickShell (`"sans-serif"` generic, per BRAINSTORM.md)
Small, but generic font fallback vs. the deliberate "Commit Mono"/Nerd Font
choice everywhere else means the shell UI doesn't visually match the rest
of the system — a small but real "this is a different app" signal every
time your eyes land on the bar. Already on your own TODO list; agrees with
cognitive-fluency framing (consistent typography lowers the perceptual
parsing cost of UI chrome).

---

## On the "quest log" idea specifically

Your instinct is right that a UI metaphor matters here, and "quest log" is
worth taking seriously rather than dismissing:

**Why it's a good fit for you specifically:**
- You already think in terms of named, purpose-built workspaces per
  app/context (the scratchpad model) — a quest log extends that same
  "one slot, one purpose, glanceable state" pattern to *tasks* instead of
  apps.
- You already have a notification system built around "list of things
  that still need action" — a quest log is that same object made visible
  and persistent instead of ephemeral.
- Games make "what do I do next" cheap to answer by design — that's
  precisely the reconstruction-tax problem in §3.

**Where the quest-log metaphor breaks down / risks:**
- Quest logs in games are curated by a designer; yours has to be
  self-curated, which means it can become another thing to maintain
  (meta-work) instead of reducing work. The `linked_todos.lua` abandonment
  is a real data point here — figure out what made maintaining it not
  stick before building v2.
- "Quest" framing implies discrete, completable units with clear done
  conditions. Real work (research, debugging, open-ended design) doesn't
  always decompose that way, and forcing it into quest-shaped chunks can
  create false completion signals or avoidance of the messy 20% that
  doesn't fit a checkbox.

**Concrete recommendation** — don't build a new bespoke system yet. Try
cheap first:
1. A single markdown file per active project (`STATE.md` at repo root,
   which you're already doing informally via `BRAINSTORM.md`/`AGENTS.md`
   pattern in *this* repo) with three sections: `Now`, `Next`, `Why`.
   Update it as the *last* action before switching context, not the first
   action after returning — this is the part that usually fails, so make
   it a tmux/nvim keybind (`<leader>state` → open+cursor-to-`## Now`) so
   the friction to update is near zero.
2. If that sticks for a few weeks, *then* consider wiring it into
   QuickShell as a glanceable widget (you already have the palette engine,
   the notification server, and Python backend scripts — the
   infrastructure to surface "current quest" in the bar already exists,
   it's not a new subsystem, just a new data source).
3. Only build a "real" task database (with priorities, due dates,
   cross-project aggregation) if the plain-markdown version proves the
   *habit* first. The habit is the hard part, not the storage format.

---

## Prioritized action list

1. **De-autostart Mailspring** — matches existing Discord/Slack pattern,
   trivial change, removes the one ambient interrupt channel. (`autostart.lua`)
2. **Decide on `cord.lua`** — disable, or time-gate using the same pattern
   as bedtime-lockout.
3. **Try the `STATE.md` + keybind experiment** for 2-3 weeks before
   building anything bigger — this directly addresses the reconstruction-
   tax problem, which is the highest-leverage gap found.
4. **Revisit why `linked_todos.lua` was abandoned** before writing a v2 of
   anything task-related — avoids repeating the same failure mode.
5. **Fix QuickShell bar contrast** for glanceable elements specifically
   (already on your BRAINSTORM.md list — just prioritizing it here from a
   focus-first angle).
6. Lower priority: evaluate whether numbered workspaces 0-9 are still
   earning their keep next to the 13 named scratchpads; consider
   ActivityWatch for passive session-length awareness if you want data
   before committing to any active-interrupt solution.
