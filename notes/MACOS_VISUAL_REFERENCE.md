# macOS Visual Match: Handoff

Last updated: 2026-10-04. This is the single current handoff; obsolete runtime
checkpoints have been removed. Implementation details are in
[the glass README](../home/features/desktop/hyprland/glass/README.md).

## Goal and Constraints

- Match macOS 27.0.1 on Linux at 3840x2160, scale 1, using original-resolution
  Mac captures for geometry, typography, contrast and material measurements.
- Focus on Spotlight/Vicinae, menu bar, menus/submenus, Control Center and
  notifications. Finder/Thunar and Dock are references, not mandatory replacements.
- Preserve Vicinae search, extensions and navigation. Preserve QuickShell's
  workspace overview and its app/location utility; rescale only if needed.
- A global app-menu mode is optional and must be reversible. Show exported
  menus only when available; otherwise fall back to workspaces. Do not fake menus.
- Do not interrupt a game or show, change the physical display's focus,
  workspace/fullscreen state, or wallpaper for tests. Use a headless output on
  the existing compositor, not a nested compositor window on the visible desktop.
- Keep editable configuration beside its owning module in this repo. Deploy
  through Home Manager out-of-store directory symlinks, including when an app
  atomically replaces files. Compiled binaries/shaders may be immutable store outputs.
- Do not commit unless asked or alter unrelated dirty work, including
  `notes/CAPTURE_PLAN.md`, Thunar settings, agent state, and unrelated host changes.
- User accepts a numeric transparency file instead of a slider UI. Do not
  build a fancy control unless requested later. Last requested model was GPT-6.1 Sol.

## Completed

- User confirmed glass works in normal Vicinae. `rehome` installed the launcher
  patches and reproducible Hyprland glass package.
- Empty launcher is a search-only pill with continuous-curvature corners.
  Search field is 640x57 at (1600,792) on the reference display: 55px search
  content plus its insets. Layer exclusion zone -1 avoids a 30px displacement
  when the menu bar is visible.
- Search uses SF Pro Display Medium at 26px, 24px magnifier and 20px horizontal
  padding. Standard root result rows are uniformly 58px with stacked subtitles,
  rather than a larger first result. Extension-specific layouts remain separate.
- News/update availability no longer prevents compact mode. Toast dismissal
  re-runs compaction so a startup toast cannot leave an empty launcher expanded.
- Glass samples actual content behind the Qt surface in the compositor, then
  applies fitted two-scale blur, tint, chroma, edge refraction, rim/outline and
  shadow. Empty fields use a capsule; expanded results use 23px continuous corners.
  Client backgrounds, borders, shadows and delegate backdrops become transparent;
  text, icons, selection and functionality remain client-rendered.
- Backdrop invalidation no longer reads damage after Hyprland consumed it.
  Commit observers use global logical surface bounds; throttled commits retain
  the dirty flag. Background changes update glass without restarting the launcher.
- Linear FP16 working-buffer conversion and shadow-alpha correction are
  implemented and visually checked on the virtual output.
- QuickShell bar is 30px tall with a 183px bottom-layer wallpaper scrim. Item
  color switches at mean top-30-row CIE L* >= 78.6 (stored normalized as 0.786).
  `wallpaperctl` samples that lightness and writes generated `displayed` state.
- Removed stale `gameDev.enable` entries from `home/hosts/*` to unblock rebuilding.

- Spotlight query state (`vicinae/spotlight-suggestion.patch`): while typing,
  the selected root result gets a soft white fill (alpha 0.17, measured +35/255
  additive); first Down turns it accent blue without moving, Up from the first
  result returns to the soft state. Field shows `query + title tail + " — Open"`
  (or `query — Title`) with a 32px 0.19-white pill (radius 8) and the selected
  icon (30px) at the trailing edge. Rows: inset 10, radius 17. Caret: 2x30 white,
  rounded, fade blink, hidden while a suggestion pill shows (Mac captures in
  `~/Pictures/macos-reference/10-spotlight-states/`). Blue state not
  screenshot-verified: test windows take no keyboard input.
- QuickShell dropdowns are layer surfaces (`bar/components/GuardedPopupWindow.qml`)
  so hyprglass draws glass: namespaces `quickshell-menu` (radius 13) and
  `quickshell-panel` (radius 22), inset 80 = `Theme.glassShadowPadding`; input
  mask is the body only. API: `anchorItem`, `popupX/Y`, `popupWidth/Height`.
  `quickshell-inbox` is transparent with a blur rule. Opaque fallback when the
  plugin is absent (`Theme.glassActive` probes `hyprctl hyprglass status`).
- Mac menu metrics in `Theme`: 24px rows, 11px separators, 5px padding, 14px SF
  Pro, #007aff highlight radius 8, menus 1px below the 30px bar. Wi-Fi menu
  and tray menu rebuilt to this; bar open-item highlight is a 22px capsule at
  white 0.09; clock uses U+202F before AM/PM.
- Fixed launcher subtitle spill after returning from a subview. Conditional
  vertical anchors stretched title height from 24px to 48px when subtitle
  visibility changed. Explicit title/subtitle y positions remove the conflict.
  Qt 6.11.2 offscreen regression: old bindings fail 75/112 states; fixed bindings
  and a gap-free y-position control pass all 112 states. Standard rows remain 58px.
- Typed search text is white; magnifier is 23px Regular at neutral 0.7 white.
  Compact placeholder now uses measured additive compositing, not 0.93-white
  source-over: encoded `min(255, backdrop + 124 * glyphCoverage)`. Client marks
  placeholder ink as gray 124 only when backend advertises `macPlaceholder` and
  helper exports `VICINAE_MAC_PLACEHOLDER=1`. Shader opt-in
  `mac_placeholder_additive` preserves ordinary caret/icons/typed text. Black,
  gray and white GPU probes produce glyph maxima 156, 246 and 255, matching Mac.
  Noncompact/fallback placeholders retain 0.93 white. Font rasterization remains
  approximate; no claim of exact text parity.
- Per-layer `mac_shadow` and `mac_outline` controls are packaged in the seventh
  plugin patch, `layer-shadow.patch`. Finite inputs are clamped to 0..1; defaults
  retain Spotlight. Menu/panel shadow 0.2, outline 0.2; Control Center shadow 0.08,
  outline 0.2. Off-screen white-backdrop Wi-Fi test, 20px below popup: shadow 1
  yields 174/255, 0.2 yields 239/255, 0 yields 255/255. Geometry/material fits remain
  approximate. Wi-Fi title uses DemiBold; MacToggle knob is pure white.
- Main Control Center has separate visual 140x64 connectivity capsules, 140x140
  media tile, and 292x64 slider platters, but now shares ONE client surface and
  backdrop sample. `mac_rects` (up to eight finite logical rectangles) renders
  independent glass islands in one pass. Separate-window opening was visibly
  staggered even after off-screen premapping; grouped surface shows all modules
  in first captured frame. No outer panel. Unsupported controls are not faked.
- Control material is no longer Spotlight's tone curve: endpoint-constrained
  affine 32/186 response, separate conditional two-scale blur fit. GPU endpoints
  match 32/186. Intermediate luma, RGB/chroma and independent shadow fitting are
  still provisional. `mac_profile="control"` selects it; Spotlight remains default.
- Fixed `quickshell-cc-detail` surface replaces mutating the controller's mapped
  namespace. Sound page is output-first, matching reference hierarchy and rows;
  Input/application mixing remains available through functional Sound Settings.
- Notification banners and Center cards now own compositor-glassed surfaces
  `quickshell-notification-card`; ordinary painted backgrounds are suppressed only
  when material is supplied. Card measurement is independent of window visibility
  to avoid viewport binding loops. Center forwards scrolling and groups card
  focus windows. Partial rows currently hide rather than clip, leaving edge gaps.
- Clear blur narrow sigma is 4.0 instead of 4.6536; nine new high-contrast holdouts
  improve, but older thin-line/low-contrast residuals remain. Tangential field now
  interpolates measured actual-tint anchors instead of disappearing at 0.5.
  Rendered clear checker proof before blur refinement: end RMS 17.20 -> 11.33,
  straight 13.15 -> 10.53/255. At tint 0.5111662: end 8.112 -> 7.968, straight
  7.863 -> 7.879. Full-tint body tangent remains unproven; existing normal rim retained.
- Geometry-first taper revision follows user's half-tint screenshot: matched
  64px checker sweep (`17-late-taper`) refits both normal and tangential fields.
  At actual tint 0.5111662, tangent amplitude is ~10.96 instead of previous ~3.7.
  GPU paired contour RMS 2.687 -> 1.383px; rim 4.440 -> 2.324px; body .371 ->
  .134px; corners 1.646 -> .738px. Clear/full endpoints preserved. Failed .63
  corner fit replaced by accepted bridge; weak upper fits retain existing field.
  Controls keep their previous normal optics rather than silently inherit retuning.
  Intensity RMS worsens 5.75 -> 6.41/255 despite visible geometry improvement.
  Remaining polarity-specific rim waveform mismatch is not fixed by blind boosts.
- Launcher font rasterization now uses 4x offscreen text layers with smooth
  mipmapped downsampling for search input (including placeholder/selection/caret),
  inline completion and result title/subtitle. Text items also use very-high
  distance-field quality. Font family, weight, size, color and logical geometry
  are unchanged; no monitor scaling or shader changes. Headless comparison against
  a 4x curve-rendered reference reduces edge-coverage RMS about 3x for headings/
  titles and 4x for subtitles. This is not proof of exact Mac rasterization.
  Texture memory/bandwidth increases; heavy extension performance remains unmeasured.
- Fixed additive placeholder AA classification after user's latest jagged-text
  comparison. Normalized-ink tolerance rejected valid RGBA8 low-alpha glyph pixels,
  switching them to dark gray source-over. Matcher now compares premultiplied
  encoded values with 2-LSB rounding budget and explicit white-ink exclusion.
  Actual GPU dark edges 81 -> 0, brightness reversals 63 -> 0; 369 AA pixels
  corrected, 210,648 background pixels and 296 core glyph pixels unchanged.
  Bounds/font/size/color declarations unchanged. Phase-aligned Mac edge RMS
  26.60 -> 19.43/255; remaining font/phase differences are not claimed fixed.
  Regression: `glass/placeholder-coverage-test.py` (five dependency-free tests).
- `rehome` deployed these changes and normal Vicinae was restarted through
  `vicinae-with-glass`. Plugin was loaded from its deployed library with ABI checks
  intact. One plugin instance remains; isolated clients/output were removed.
- Runtime tray-menu null-entry warnings on removal/reload were guarded at delegate
  bindings and leading-column detection. Subsequent normal QuickShell reload
  loaded successfully without new tray null-entry warnings.

## Transparency Control

Edit `home/features/desktop/quickshell/config/theme/glass-tint` in this repo.
Its deployed alias is `~/.config/quickshell/theme/glass-tint`, through the
existing Home Manager directory symlink. It contains a single number:

- `0`: clear, most transparent.
- `0.5`: intermediate.
- `1`: fully tinted, least transparent. This is also the fallback if unreadable.

QuickShell watches the file and updates the compositor through guarded
`hyprctl eval`; changes require no rebuild or restart. Lua reads the same file
when configuring the backend. Live changes were verified. The file's current
contents are authoritative; do not reset the user's value while testing.

The incorrectly placed `~/.local/state/wallpaper/glass-tint` was removed.
Do not recreate it or add a compatibility alias. Tint does not drive the
menu-bar item-color/scrim contrast model.

## Loading and Deployment

Hyprland autostart runs `vicinae-with-glass server`. The helper loads the
compiled library once through external hyprctl IPC if the backend is missing,
waits for an active layer backend, then sets `VICINAE_MAC_GLASS=1`. Without an
active backend it retains normal Vicinae blur. `config/glass.lua` only configures
an already-loaded plugin; it does not load one while parsing configuration.

Window glass is disabled. Normal glass application is restricted to `vicinae`,
`quickshell-menu`, `quickshell-panel`, `quickshell-cc-detail`,
`quickshell-notification-card` and capability-gated `quickshell-cc-group`.
Old pill/tile namespace declarations remain for the already-shipped integration.
The transparent `quickshell-cc-host` is excluded. The binary's isolated-test
default namespace is `glasstest`.

The loader originally conditionally declared `hl.plugin.load()` only when its
namespace was absent. Because that call declares config-managed loading, later
reloads alternated loading and unloading, causing a stall; a reboot occurred.
Do not reintroduce that conditional declaration. The external startup helper
avoids this loop. Config-only reload was subsequently verified to return
promptly, retain the active backend and maintain healthy memory usage.

`config-lifecycle.patch` retains Lua layer declarations through post-reload
filter parsing. All eight plugin patches and the upstream BSD-3-Clause license
are included in the Nix package. Compositor plugins require matching headers
and runtime ABI; never bypass compatibility checks.

## Source Map

All paths below are relative to this repo unless prefixed with `~`.

| Area | Files |
| --- | --- |
| Glass package and shader changes | `home/features/desktop/hyprland/glass/package.nix`, its eight `.patch` files, and `README.md` |
| Glass configuration and startup | `home/features/desktop/hyprland/config/glass.lua`, `appearance.lua`, `autostart.lua`, and owning `default.nix` |
| Vicinae package, helper and UI patches | `home/features/desktop/vicinae/default.nix`, `spotlight-layout.patch`, `spotlight-glass.patch`, `spotlight-suggestion.patch` |
| Editable Vicinae settings/theme | `home/features/desktop/vicinae/config/`, `spotlight.toml` |
| Shared tint and synchronization | `home/features/desktop/quickshell/config/theme/glass-tint`, `Theme.qml` |
| Bar/scrim | QuickShell `config/bar/Bar.qml`, `BarWindow.qml`, `BarScrim.qml`, `components/shaders/bar-scrim.frag`, and owning `default.nix` |
| Wallpaper sampling/state | `home/features/desktop/wallpaper/src/main.rs` |

The library is deployed at `~/.local/share/hyprglass/libhyprglass.so` as a
Home Manager-managed store link. Normal deployed code has no dependency on
`/tmp/opencode`; use `rehome` for build-controlled changes.

## References and Evidence

Archive: `~/Pictures/macos-reference/`. Its `README.md` indexes capture categories
and coordinates. Keep new images labeled with element, wallpaper, tint and state.

- `00`-`02`: setup and early diagnostics, including stale/inactive-display cases.
- `03-menubar-contrast/FINDINGS.md` and `curves_lut.json`: measured contrast,
  scrim tone curves/fade, and menu-bar-background mode. Start here for bar work.
- `04-ui-matrix/`: detailed menus/submenus, Control Center pages, notifications,
  Spotlight and other status surfaces on photo-current.
- `05-wallpaper-tint-matrix/`: invalid transparency labels; every capture was
  actually tint 1. Do not compare these as different slider positions.
- `06-finder-dock/`: reference-only Finder/Dock views.
- `07-verified-transparency-matrix/`: 162 captures, six wallpapers x verified
  tints 0/0.5/1 x nine surfaces. Spotlight crop: (1200,600,1440,700).
- `08-spotlight-glass/`: extra gray ramps, colors, line/edge/grid patterns and
  empty/query states. Additional gray/color tints 0.25 and 0.75. Empty crop:
  (1500,700,840,260), around field (1600,792,640,57). Contaminated shots were redone.
- `09-linux-spotlight/`: actual isolated Vicinae proof captures at 3840x2160,
  with a README distinguishing final UI from intermediate material tests.
- `10-spotlight-states/`: Mac caret/query captures. Some arrow captures contain
  no launcher or unchanged selection and are not proof of blue-state navigation.
- `11-linux-dropdowns/`: separate Control Center platters, three shadow-strength
  comparisons over white, corrected launcher rows, and archived Qt regression
  harness/delegate snapshot. Test bus lacks real media/audio services; no physical
  keyboard or pointer input was used. Its README records these limitations.
- `12-warp-calibration`, `14-quadrature-warp`, `15-high-signal-warp`: richer Mac
  pattern/phase evidence with actual tint values and verified restoration.
- `batch13-control-material`: independent Control Center endpoint/blur evidence.
- `16-linux-glass-proof`: final foreground, grouped presentation, notification/
  Sound backgrounds and mid-tint warp, with explicit caveats.
- `17-late-taper`: matched 64px checker/shifted-checker/step sweep, verified actual
  tints and exact Mac state restoration. `18-linux-taper`: old/new GPU geometry,
  accepted table, rejected waveform trials and remaining limitations.
- `19-font-rasterization`: rendering-mode comparison, actual before/after launcher
  captures and scope/overhead notes. Naive supersampling without mipmaps was worse.
- `20-placeholder-aa`: actual before/after compositing fix, quantization/GPU reports
  and preserved-glyph/background proof. Supersampling alone could not fix this bug.
- `wallpapers-test/` and `scripts-mac/`: exact reference backgrounds and helpers.

Recorded comparisons against Mac captures, excluding text:

| Test | Interior RMS | Rim RMS | Shadow/outside RMS |
| --- | --- | --- | --- |
| Tinted gray 128, SDR | 0.25/255 | 3.18/255 | 1.39/255 |
| Tinted gray 128, linear FP16 | 0.36/255 | 3.26/255 | 1.57/255 |

Tinted checkerboard interior RMS was 2.45/255. Clear checkerboard interior
improved from 25.4 to 11.8/255 with tint-dependent refraction. Edge/outline maxima
remain larger. These averages do not establish pixel-perfect parity. FP16
checks used an invisible wide-color output, not a launcher capture over the
physical HDR display. User confirmation establishes normal launcher usability.

## Remaining Work

1. PRIORITY: user half-tint comparison (2026-10-04, Mac left/Linux right,
   `~/Pictures/Screenshots/Screenshot from 2026-10-04 10-43-48.png`) contradicts
   old taper: Mac retains substantial warping at half tint, Linux lost most of it.
   Geometry-first revision is installed and halves paired GPU contour error, but
   does not establish exact parity. One rim-edge polarity still differs by ~6px
   while opposite edge/midpoint aligns. Tested tone/blur ordering, separate branch
   warps and asymmetric kernels did not resolve it without other regressions.
   Next work must address waveform shape, not simply increase tangent amplitude.
   Earlier aggregate RMS/phase gains are not proof of visible geometry matching.
   Higher-signal probes at tint 1 did not identify a reliable body tangent; do not
   invent strong full-tint warp. Clear blur still has thin-line/low-contrast limits.
   Finish font rasterization and foreground comparisons beyond placeholder.
2. Complete Control Center ramp/RGB and shadow calibration; endpoint/periodic
   fits are not proof of exact material across wallpapers. Validate real
   pointer/keyboard input, outside dismissal, Escape, media and sliders on the
   normal bus. Keep unsupported Mac features absent rather than fake them.
3. Refine remaining nested panels and notification scrolling/clipping/calendar.
   Tray menu is untested on private bus. Finish bar item geometry comparisons.
   Battery is explicitly last: user wants exact Mac menu, not retained history
   chart; this desktop has no battery. Existing battery layout is not final.
4. Ask whether to disable desktop wallpaper workspace blur. Current Hyprland
   workspace rule enables blur, with vibrancy 0.1696. This alters wallpaper
   appearance unlike macOS and affects matching; do not silently change it.
5. Validate bar scrim exactly on the same wallpaper and color-management state,
   after the blur decision. Earlier Linux comparison was roughly 13/255 off
   with blur enabled; use the measured Mac model rather than that rough result.
6. Optional reversible global app-menu mode: use exported menus when available,
   otherwise workspaces. No global-menu/dbusmenu bridge has been implemented.
7. Preserve the workspace overview; adjust scale/spacing only for visual coherence.
8. Measure animated-background performance and resample-rate behavior, finish
   functional/visual comparisons, and update evidence/index with remaining gaps.

Numeric tint control is complete. A slider UI is not required and is not backlog.

## Testing and Pitfalls

- Discover the live compositor with `hyprctl instances -j`; PIDs, signatures and
  generated store paths expire. Do not select stale directories with `ls -t`.
- Configure a test output before creating it, then capture only that output:

```sh
hyprctl eval 'hl.monitor({output="GLASS-TEST",mode="3840x2160@60",scale=1,position="12000x0",cm="srgb",bitdepth=8})'
hyprctl output create headless GLASS-TEST
nix-shell -p grim --run 'grim -o GLASS-TEST /tmp/opencode/test.png'
```

- Do not recreate an existing output or infer that an old test process still runs.
  Stop verified test clients before removing their output; do not let them fall
  back to the physical display.
- A separate Vicinae test must isolate HOME and all XDG storage/runtime paths,
  use a private D-Bus session and an absolute live Wayland socket. `--config`
  alone is not isolation. Never use `--replace` or `make dev` for this purpose.
- QML-only test screen selection fell back to the physical monitor. The working
  test patch set QScreen and LayerShellQt::Window::screen in C++ before showing
  any window, failed closed if output was absent, and requested no keyboard focus.
  Do not deploy these test-only output restrictions to normal Vicinae.
- Isolated fontconfig can lose Home Manager SF fonts. Validate font resolution
  in the isolated environment, not only with the normal user's `fc-match`.
- This Hyprland fork rejects legacy `hyprctl keyword` with `unknown request`.
  Use `hyprctl eval` for configuration and Lua dispatch syntax for commands:
  `hyprctl dispatch 'hl.dsp.exec_cmd("cmd")'`.
- Process names may be wrapped. Stop a verified PID, not a broad `pkill -f`
  pattern that can also kill the invoking shell. No historical PID is authoritative.
- Plugin unload takes its loaded library path, not plugin name. Verify plugin
  list is empty before loading replacement; verify exactly one instance afterward.
  Do not leave a test-library path as normal startup configuration.
- Check graphical session `cgroup.freeze` before blaming IPC hangs on rendering.
  This session was explicitly frozen during tests; do not unfreeze it unasked.
- Headless output can be DPMS-off and return black captures. Wake only the named
  test monitor, never global DPMS. Test windows must use keyboard None as well as
  disabled focus grabs. A long isolated XDG_RUNTIME_DIR can exceed Unix socket
  path limits; hyprctl probe needs real runtime path, without sharing app storage.
- Wallpaper rotates. Read generated `~/.local/state/wallpaper/displayed` before
  comparing pixels; an earlier alleged scrim failure was a wrong-wallpaper comparison.
- Mac SSH alias is `macos`, account `anthonygreen`. `Ref4K` is primary 3840x2160
  at 1x; capture with `screencapture -x -D 1`. Keep it active: inactive-display
  menu-bar items dim to approximately 35% opacity.
- After changing Mac wallpaper, toggle "Show menu bar background" on then off
  to refresh adaptation. Glass tint did not change menu-bar pixels in measurements.
- Remote shell is zsh. Use bash for capture scripts, full Homebrew binary paths,
  and `=` before negative cliclick coordinates, such as `c:=-1208,825`.
- Mac app activation can block while a menu is open; close panels and focus by
  clicking when possible. Spotlight window owner is `Siri`; reopening restores
  its query, so clear it and verify empty-state bounds before labeling captures.
- Verify actual `defaults read -g NSGlassTintAmount` after Mac slider automation;
  do not trust filenames or old local helper copies. Current Mac helpers live in `~/ref/`.

## External Artifacts

`/tmp/opencode/` contains temporary prototypes, isolated test configurations,
fit scripts (`glass_model`, `fit_blur`, `fit_joint`, `fit_shared`, `fit_rim`,
`fit_shadow`, `chroma_fit`) and results. They may disappear and are not deployed
dependencies; fitted constants are preserved in the repo's shader patches.
Shared refraction fitting was worse than per-tint fitting; do not adopt blindly.

Screenshots, measurements and Mac capture helpers intentionally live in the
reference archive and Mac `~/ref/`. Generated wallpaper state belongs under
`~/.local/state/wallpaper`; editable transparency configuration does not.
All live editable glass configuration is repo-backed. No commit has been made
for this work.
