# macOS Glass

macOS-fitted glass is packaged by Home Manager, loaded by `vicinae-with-glass`,
and configured for Vicinae and QuickShell dropdowns through `config/glass.lua`.
Window glass remains disabled; other applications and the menu bar are not glassed. Measurements
were captured on macOS 27 at 3840x2160,
scale 1, dark appearance. This is a working approximation, not pixel-perfect
parity across every wallpaper and transparency value.

Compositor rendering is necessary for live blur and refraction of other
applications behind a Qt surface. A QML ShaderEffect cannot sample another
process's backdrop. The shader can be reused for other transparent layer
surfaces; their material profiles and geometry still need separate validation.

## Source and compatibility

`dock-ink-regions.patch` limits Dock's gray-124 additive ink to the running-dot
band and separator gap. Icon artwork must always use ordinary premultiplied-over
composition: gray pixels in Trash (especially when pressed) previously matched
the ink marker and produced bright, blue-tinted contour lines. Launcher ink is
unchanged. Region geometry follows `Dock.qml` / `DockTile.qml`; update the patch
and `test-dock-ink.py` if that layout changes. The EGL test exercises actual
compiled shaders with empty/full Trash, held/normal icons, SDR/HDR, and AA ink.

Pinned Hyprglass upstream: `a54e7cd0232ca62a394aebebd553358dc6592652`.
The patch first reverses upstream commit
`b14733f81f6868f6bbbac7c2e2c47a8f665756eb`, which added the workspace-presentable
argument to window-decoration drawing. That reversal is required for the
matching Hyprland fork's two-argument decoration API. The patches include
`src/MacGlassParams.hpp`, fitted shader parameters, backdrop invalidation fixes,
encoded-space blur, and linear-buffer shadow correction.

Use the matching Hyprland fork and revision for both build headers and runtime;
do not assume compatibility with arbitrary upstream Hyprland or another ABI.
Compositor plugins run inside Hyprland: an incompatible plugin can crash the
desktop session. Do not bypass ABI checks.

## ARM Layer Backend

Hyprland's function-hook implementation returns false on non-x86_64 builds.
Finding `renderLayer` therefore does not make its hook usable on ARM64: the old
plugin reported `hook_missing`, and launcher startup correctly refused glass mode.

On aarch64 only, the Home Manager module appends `../portable-layer-render.patch`
to the pinned compositor package, installs that package, and builds Hyprglass
against its headers. `portable-backend.patch` selects this backend on ARM64;
x86_64 retains the existing function hook and unmodified compositor package.

The fork exports `hyprland_register_layer_render_v1` and
`hyprland_unregister_layer_render_v1`, resolved by the plugin with `dlsym`.
This is an architecture-neutral C symbol interface with a versioned, matching
C++ callback ABI, not a general stable C ABI. No machine-code hooks, new virtual
methods, or compositor object-layout changes are involved. The single-owner
registry rejects occupied registrations and unregisters only a matching owner
and callback. Calls and registration run on the compositor's main thread.

The callback receives the original render continuation directly. It wraps the
unchanged compositor render body without recursively entering the callback.
Both backends share the existing glass wrapper: snapshot/foreign-render guards,
popup arguments, normal early returns, pre/post glass passes, and scoped blur
suppression remain intact. Plugin exit unregisters before tearing down state;
failed initialization also unregisters before its library can be unloaded.
Compositor plugin teardown independently clears callbacks owned by the unloaded
handle, including forced ejection/fatal faults that skip `PLUGIN_EXIT`.
Diagnostics treat successful portable registration as an available layer backend,
while still checking configuration and shader failure. ABI checks are unchanged.
Missing exports or an occupied registry produce a warning, never an ARM hook fallback.

This fixes layer glass only. Optional subsurface item glass still uses the existing
`CRenderPass::add` hook and is unavailable on ARM64; window decorations use their
existing non-hook path. Neither optional feature is enabled by this fix.

Patch-application and callback regression checks do not prove ARM GPU rendering.
After an explicit future rebuild/restart, verify `hyprctl -j hyprglass status`
reports `features.layers.active = true`, open Vicinae/QuickShell glass surfaces,
and check popups, close snapshots, config reload, and plugin unload/reload.

## Apple glass for app windows (`apple-glass.patch`)

A port of QuartzCore's `glass_background` shader (macOS 27, decompiled in the
MacOS Theme session's `23-sidebar-glass`), applied under part of an app
window. The client names a built-in material (`apple-sidebar`: Finder's
sidebar, fitted to 1.2/255 on 44 wallpapers) and an explicit shape on its
toplevel surface through `hyprglass_item_v1`. The plugin then draws that
material beneath the surface, disables Hyprland's own blur for that window,
and gives shape corners on the window's corners the window rounding.
No config switch is involved; window glass and `subsurfaces` can stay off.

Clients leave the sidebar transparent only with manager version 2 or newer.
The toolbar extension below advertises manager version 3 through a separately
versioned resident helper, so it can coexist with helpers from older plugin
loads. Layer glass can select Apple presets through `apple-layer.patch` below.

Offline shader check: `24-apple-glass-hyprglass/harness.py` runs
`appleglass.frag` headless against the numpy model and the Mac captures.

## Apple layer presets (`apple-layer.patch`)

The twelfth patch routes `hyprglass.layer(namespace, { mac_apple = name, ... })`
through AppleGlass. Presets `apple-dock`, `apple-menu`, and `apple-widgets` use
decoded Apple GPU uniforms at glass diffusion 1. The renderer adds continuous
corners, ovalized normals, the 13-tap QuartzCore backdrop pyramid, and the
diffuse key/fill highlight with vibrant-color-matrix blending. Existing inset,
radius and rectangle geometry remains available; client content is composited
above the glass, including additive placeholder ink.

Dock, Vicinae, dropdowns and panels select these presets in `glass.lua`.
The context work (Kanban) widget selects `apple-menu`; dictation selects the
higher-contrast `apple-widgets` material.

## System presets (`apple-system-presets.patch`)

`apple-control-center` and `apple-notification` (in `AppleSystemPresets.inc`) come
from the running macOS 27.0.1 ControlCenter and NotificationCenter processes, read
through LLDB: live CAFilter inputs, highlight effects and vibrant colour matrices
(`MacOS Theme/27-real-glass/data/live-{cc,nc}-final.json`). Those inputs were
replayed through Apple's CARenderer, and the GPU uniforms it produced were decoded
into these presets. No screenshot fitting is involved.

Verified in nested Hyprland: interiors over black/gray/white are CC 32/118/204 and
notifications 32/83/108. Apple's own renderer gives identical values for the same
inputs.

Wi‑Fi uses two materials on macOS too (captured live, `data/live-wifi-menu.json`,
`data/live-cc-wifi.json`). The menu-bar Wi‑Fi menu is menu material (`apple-menu`,
used by the bar popup). Wi‑Fi opened inside Control Center is Control Center
material (`apple-control-center`, used by `quickshell-cc-detail`). Apple scales
refraction/bleed/shadow heights with surface size, while these presets use fixed values.

Not reproduced yet: on macOS, ControlCenter draws a separate 50 pt, 10% black
shadow layer beneath its glass, and the glass samples that darkened backdrop
(real white reads 186). NotificationCenter has similar custom shadow layers. This
backdrop work is a separate pass. Do not fold it into the preset tone.
Apple presets use dark appearance. The shared `quickshell/theme/glass-tint`
file now controls their glass diffusion live: Dock/widgets vary blur and blur-fill;
menus also interpolate Apple's measured face matrices and luma compression.
Values are clamped to 0..1, and layer `mac_tint` overrides still take precedence.

`shared-tint.patch` extends this resolver to Control Center, notifications and
Finder's active/inactive toolbar and sidebar. Window-item passes resolve the same
shared value at draw time instead of retaining a fixed preset. The opaque
`apple-toolbar-base` backing plane is intentionally unchanged.

Apple DesignLibrary diffusion sweeps (0, .125, .25, .375, .5, .625, .75, .875, 1)
confirmed Control Center's fixed face matrix, blur radius `4*min(2*t,1)` before
backdrop scaling, and normal blur-fill `max(2*t-1,0)`. Notifications use regular
face-matrix/fill interpolation while retaining their own .4 holding tone,
geometry and rim. Inactive toolbars keep Finder's captured black=.08 endpoint.
Sidebar fill follows the sidebar response (.25/.5/1 at clear/half/full), retaining
its existing face and bleed calibration. The fitted Dock tooltip carries the
fitted profile's tint deltas onto its measured full-tint LUT and blur endpoints;
this remains a fitted approximation, not an extracted Apple tooltip recipe.

Focused render regression (Pillow, Hyprland, QuickShell and grim required):

```sh
python test-shared-tint.py /nix/store/.../lib/libhyprglass.so --strata
```

This creates a temporary hidden parent output hosting a private nested compositor,
then cleans up its processes/output and restores workspaces. It checks all eight
translucent Apple presets, fitted tooltip, per-layer tint override, return to full
tint, and (with `--strata`) real window sidebar/toolbar regions. `GRIM_BINARY` can
select a matching grim executable. Clear/half/full renders and actual Strata
window regions passed with plugin 0.9.7; return-to-full card pixels were identical.

Evidence and harness: `MacOS Theme/27-real-glass`. Menus versus CARenderer have
mean error 0.07–0.43/255; widgets 0.07–0.30/255. Dock checker/stripes versus the
real Dock have mean error about 2/255, with larger residuals at end caps. Nested
Hyprland versus the offline harness differs at most 2/255 on tested checker and
photo regions. These measurements do not establish HDR or arbitrary-scale parity.

## Finder toolbar (`apple-toolbar.patch`)

Protocol version 3 adds up to 16 independently named rounded material regions
beside the original sidebar region. Changes latch on the surface commit;
removal, helper stop/restart, and surface destruction have a C regression check
in the package's `checkPhase`. Each region owns its backdrop cache. Helper ABI 2
uses a separate exported symbol to avoid reusing an incompatible resident helper.

`apple-toolbar`, `apple-toolbar-inactive`, and `apple-toolbar-base` reproduce
the live Finder toolbar recipe extracted through LLDB, then decoded from Apple
CARenderer GPU uniforms. Active inner refraction is -18/9, outer refraction
16/16; inactive outer refraction/highlight opacity is zero. The backdrop scale
is 0.125. These are toolbar-specific settings, not the generic menu preset.

Strata's `finder-toolbar.patch` selects these materials on focus changes and
uses extracted 13pt SF symbols. Search expands to a 325px cap and collapses to
a 36px button when its calculated width falls below 180px. The measured formula
is 0.75 * toolbar width - 478, based on Finder's 156px sidebar. Version 2 keeps
the CSS toolbar fallback; version 1 keeps opaque fallback for all client glass.

Release Nix artifacts passed private nested-Hyprland captures at window widths
800, 1000, 1120, and 1400, plus inactive 1400. The owner approved temporary
hidden-output hosting after fully isolated GPU backends failed allocation;
test windows/output were removed afterward. Offline masked comparison against
CARenderer gives mean maximum-channel error below 0.8/255 on uniform inputs and
1.8/255 on tested patterns. Edge differences remain; this is not pixel-perfect
parity across backgrounds or sidebar widths. Evidence and reproduction notes:
`MacOS Theme/28-strata-toolbar/README.md` in the session archive.

## Per-layer materials (`dock-material.patch`)

Lua `mac_material` on `hyprglass.layer()` overrides parts of the fitted
profile for one namespace: `lut` (17 encoded outputs at g = 0,16,...,240,252),
`chroma`, `blur = {s1, s2, w2}`, `refraction = {amplitude, width, power}`,
`rim = {r0, rc, a1, l1, l2, side, k}` and `outline_side_power` (outline alpha
times |normal.x|^power: side-only outlines). Lengths are logical px. Unknown
keys are ignored by older builds, so the Lua stays loadable.

The patch also edge-extends the background sample past the monitor edge
instead of clearing it to black. Before, a layer whose shadow padding left the
screen (the Dock, top-bar menus) blurred black into its glass near that edge.

The Dock (`quickshell-dock`) and its label (`quickshell-dock-tip`) use this.
Measurements and fit: MacOS Theme session `26-dock/README.md`.

### Dock hover labels (`dock-tooltip.patch`)

`mac_material.dock_tooltip = true` renders a single 26 px circular capsule with
a rounded 7 px pointer. The configured glass box includes both; the pointer
uses the body's backdrop, tint, refraction and rim. The hidden attachment edge
is excluded from distance/rim calculations to avoid a seam through the pointer.
This measured silhouette replaces the separate, flat-colored client triangle.

Quickshell uses icon-sized hover targets with gaps between adjacent labels;
click targets remain whole slots. A dedicated `no_anim` layer rule prevents
Hyprland from sliding the reused tooltip surface between icons. Label ownership
uses item identity, so late exits from identically named apps cannot hide the
new tooltip. QML regression: `quickshell -p ../quickshell/test_dock_tooltip.qml`.

`test-dock-tooltip.py LIBRARY REFERENCE_DIR OUTPUT_DIR` compiles the shader
embedded in the built library and compares capsule edges and pointer against
`26-dock/mac/hover-{black,gray,white}.png`, excluding text. Measured mean errors:
4.04, 3.92 and 6.03/255 respectively with the corrected 127 px reference body.
That comparison excludes text. Typography is separately checked using
`quickshell/test_dock_label_render.qml` and `test_dock_label_appearance.py`:
14 px SF Pro, optical size 17, -0.25 px tracking, native unhinted rendering,
18 px baseline and 13 px side padding. Fixed-placement text coverage RMS
improves about 60% against three Mac backgrounds. Six CoreText-measured label
advances agree within 0.6 px; this is not pixel-perfect text rasterization.
Evidence: `MacOS Theme/26-dock/typography/README.md`. Precise reveal timing and
physical HDR parity remain unverified.

### Dock menus (`dock-menu.patch`)

`mac_material.callout = { x, height }` adds a pointer below an Apple-material
(`mac_apple`) body: tip `x` pt from the body's left edge (negative: from the
right), `height` pt tall. The configured glass box includes the pointer. The
half-profile is measured from the macOS 27 Dock menu at 2x; the body's bottom
edge across the pointer is treated as interior so depth, refraction and rim have
no seam. A 0.6-alpha, 1 px dark rim (0.5 pt at 2x) is added outside downward-facing
edges, weighted by n.y², so the side outline continues round the tip as on macOS.
`quickshell-dock-menu` and `quickshell-dock-menu-end` use it.
`test-dock-menu.py LIBRARY REFERENCE_PGM OUTPUT_DIR` compiles the installed
shader and compares its contour with `MacOS Theme/29-dock-menu/mac/
trash-pointer-2x.pgm`: mean 0.34 pt, max 0.69 pt. Only the left-anchored case is
rendered by that test.

## HDR screenshots and screensharing (`hdr-mirror.patch`)

The matching Hyprland fork renders HDR displays and SDR captures through two
framebuffer attachments. Its ordinary surface shaders write both; custom glass
shaders must do the same. Writing only location 0 leaves location 1 undefined,
corrupting glass and redirected shell content in screenshots and screen shares.

Apple glass, its client-surface composite (including additive placeholder ink),
and the fitted glass/tooltip shader now write location 1 explicitly. The capture
output unpremultiplies the linear working color, removes the monitor's SDR
luminance scaling, encodes actual sRGB, then premultiplies again. Display output
is unchanged. SDR working buffers retain their original encoded values.

Focused GPU regression, using `moderngl` and `numpy`:

```sh
python test-hdr-mirror.py /nix/store/.../lib/libhyprglass.so [PREVIOUS_LIBRARY]
```

This renders the actual packaged shaders into separate floating-point display
and capture attachments. It checks 27 combinations of SDR/HDR, SDR white levels,
gamma 2.2, opacity, translucent ink and additive placeholders. An optional old
library verifies unchanged display pixels. Version 0.9.8 fails this capture
check; 0.9.9 passes. This is GPU attachment-level proof, not a physical-display
measurement or an end-to-end PipeWire recording.

## Manual application and build

In a separate Hyprglass checkout at the pinned upstream revision:

```sh
git checkout --detach a54e7cd0232ca62a394aebebd553358dc6592652
for patch in experimental hdr-encoding linear-shadow refraction launcher-shape config-lifecycle layer-shadow surface-material portable-backend apple-glass dock-material apple-layer apple-system-presets apple-toolbar capture-target shared-tint dock-tooltip hdr-mirror; do
    git apply --check "/etc/nixos/home/features/desktop/hyprland/glass/$patch.patch"
    git apply "/etc/nixos/home/features/desktop/hyprland/glass/$patch.patch"
done
cp /etc/nixos/home/features/desktop/hyprland/glass/AppleSystemPresets.inc src/
```

Apply the complete patch once; do not separately reverse `b14733f` first.
Build the patched source against the matching fork, not generic Hyprland headers.
`package.nix` provides the reproducible build recipe: fixed upstream revision
and source hash, all patches in the order above, and an explicit matching
`hyprland` argument.
The Hyprland Home Manager module imports it and deploys the immutable compiled
library at `~/.local/share/hyprglass/libhyprglass.so`. Its owning Lua configuration
remains editable in the repository. Use `rehome` to rebuild.
For a manual ARM64 build, first apply `../portable-layer-render.patch` to the
pinned Hyprland source and use that patched compositor's installed headers.

## Integration

- Window glass is off (`plugin:hyprglass:enabled = 0`).
- The binary's test default is namespace `glasstest`; normal Lua configuration
  restricts glass to `vicinae`, `quickshell-menu`, `quickshell-panel`,
  notification cards and Control Center group/detail surfaces. Old pill/tile
  declarations remain for the shipped separate-window integration.
- A 110px inset reserves space for the shader's shadow. Vicinae uses a fixed
  28.5px radius: half the 57px empty field's height, retained for expanded results
  so the top corners do not change shape. Negative radius still selects automatic
  capsule/23px rounding for other callers.
- `plugin:hyprglass:mac:tint` defaults to `1.0`; the fitted slider range is `0..1`.
- Lua layer options `mac_inset` and `mac_radius` select the fitted shader and
  alpha-mask redirect. Runtime layer configuration commits immediately.
- `layer-shadow.patch` adds finite, clamped `0..1` per-layer `mac_shadow` and
  `mac_outline` alpha scales. Defaults of 1 preserve Spotlight. Menus/panels
  use shadow 0.2 and outline 0.2; Control Center platters use shadow 0.08 and
  outline 0.2. These are visual approximations, not independent material fits.
- `surface-material.patch` adds up to eight `mac_rects` in logical body coordinates
  (`{x,y,width,height,radius}`), sharing one surface/sample/pass but drawing separate
  glass islands. This eliminates independent-window Control Center presentation
  stagger. Rectangles beyond the body bounds are skipped for optional rows.
- QuickShell reserves 80px for dropdown shadows. Main Control Center has 140x64
  connectivity capsules, 140x140 media tile, and 292x64 Focus/slider platters at radius
  32 on one grouped surface. Transparent controller remains excluded from glass;
  fixed detail surface avoids changing namespace on an already-mapped window.
- Do Not Disturb uses the Golden Gate Focus control's crescent, white active
  circle and purple accent; its active menu-bar indicator is a plain crescent.
  References: Apple's [Control Center image](https://ipcdn-web.apple.com/assets/v2/web/a973038b-6700-4b72-8c34-87834987bdd6)
  and [enabled Focus/menu-bar image](https://ipcdn-web.apple.com/assets/v2/web/8fa5393c-b12e-483a-b3c0-420d53c65d42)
  from the macOS 27 guides. The toggle suppresses every notification urgency,
  retaining non-transient history without replaying banners when disabled.
  State survives QuickShell hot reloads; a fresh process starts with DND off.
  Verify: `python3 -B -m unittest test_notifications -v` from `quickshell/`.
- `mac_profile="control"` selects independent endpoint-constrained tone/blur:
  black/white interiors about 32/186 across measured tints, unlike Spotlight.
  Intermediate luma/chroma and shadows remain approximate, not complete fits.
- Optional `mac_tint` is clamped 0..1; absent value inherits the user's shared
  file. Used for isolated calibration without changing normal UI transparency.
  `mac_tangential` disables/enables bounded fitted tangential displacement.
- `mac_placeholder_additive` opts compact Spotlight into marker-specific encoded
  additive ink: gray-124 client glyph + background, clipped to white. `macPlaceholder`
  status enables startup helper's `VICINAE_MAC_PLACEHOLDER`; old clients retain
  normal compositing. Typed text, caret and icons are not treated as placeholders.
- Marker matching tolerates absolute RGBA8 error in premultiplied encoded space.
  Comparing normalized ink with fixed tolerance rejected low-alpha antialiased
  glyphs and produced dark notches. White-ink exclusion and HDR conversions remain.
  Run `python3 placeholder-coverage-test.py` for focused regression proof.
- Plugin initialization does not call `HyprlandAPI::reloadConfig()` itself;
  the host schedules a config reload after plugin loading.
- `vicinae-with-glass server` checks for the backend and, if missing, loads the
  deployed library once through external hyprctl IPC. It waits for an active
  layer backend before setting `VICINAE_MAC_GLASS=1`; otherwise normal blur remains.
- `config/glass.lua` only configures an already-loaded plugin. Do not
  conditionally declare `hl.plugin.load()` based on namespace absence: the
  config-managed load/unload cycle caused a reload stall. External startup
  loading avoids that loop; config-only reload has been verified afterward.
- `config-lifecycle.patch` retains Lua layer declarations so post-reload
  filter parsing does not discard fitted material settings.
- Vicinae's client background, border, shadow, and delegate backdrops become
  transparent in glass mode; text, icons, selection, navigation and extensions
  remain client-rendered.
- Shared editable tint configuration is
  `home/features/desktop/quickshell/config/theme/glass-tint`
  beside the owning module, exposed through the existing Home Manager directory
  symlink at `~/.config/quickshell/theme/glass-tint`. Lua and QuickShell Theme read
  that same repo-backed file. `Theme.setGlassTint()` writes it and updates the
  compositor.
  Values range from 0 (clear) to 1 (tinted); intermediate values apply live with
  no rebuild or restart. The user explicitly accepts the numeric file, so a
  slider UI is not required. Do not recreate the removed runtime-state copy.

## Known limitations

- HDR encoding correction is verified with a linear FP16 working buffer: the
  first Gaussian pass converts linear work-buffer samples to encoded sRGB; later passes stay
  encoded; composite converts glass back to the work-buffer space. Black-shadow
  alpha is corrected for linear compositing. FP16 visual measurements came
  from the virtual output, not a physical-HDR-display capture.
- Consumed-buffer-damage invalidation is fixed: commit observer uses global
  logical surface bounds rather than reading damage after Hyprland consumed it.
  Changing the test wallpaper now updates glass without a launcher restart.
- Throttled commits now retain the dirty flag, avoiding a stale final frame.
  Performance on animated backgrounds and a hard resample-rate limit deserve
  further measurement.
- Clear-glass edge distortion, outline/antialiasing, foreground contrast at
  some tint values, and platform font rasterization still differ from macOS.
  Recorded averages are not proof of pixel-perfect parity across displays.
- Bounded tangential warp now spans clear/mid tints using actual-tint phase fits,
  not a cutoff at 0.5. Some diagonal-edge residuals remain. Full-tint body tangent
  was not reliably identified; existing normal-rim refraction remains at tint 1.
- User's 2026-10-04 half-tint comparison shows this taper is still too aggressive:
  macOS retains substantial distortion while Linux nearly lost it. New matched
  64px-checker geometry fit refines both normal/tangent fields; half-tint paired
  GPU contour error falls 2.687 -> 1.383px, rim 4.440 -> 2.324px. Clear/full
  endpoints preserved; failed intermediate/upper fits use accepted bridges or
  existing fields. Residual rim waveform asymmetry remains, so this is not exact
  calibration. Visible geometry is assessed separately from pixel intensity RMS.
- Clear narrow blur sigma 4.0 improves new high-contrast holdouts, but older
  thin-line/low-contrast patterns still have regressions. No all-pattern parity claim.

## Verified So Far

- Matching fork builds and loads the shader; window glass remains disabled.
- At tint 1 on uniform gray 128, glass interior RMS error is 0.25/255,
  rim 3.18/255, shadow/outside 1.39/255 against the Mac capture. These region
  averages do not imply exact corner or outline parity.
- Checkerboard interior RMS error is 2.45/255; its rim and outline are less
  accurate. Clear-tint checkerboard interior RMS improved from 25.4 to 11.8/255
  with tint-dependent refraction; those edges still need refinement.
- Linear FP16 gray-128 comparison: interior RMS 0.36/255, rim 3.26/255,
  shadow/outside 1.57/255 after shadow-alpha correction.
- Actual isolated Vicinae search UI renders on this material. Its test build
  has transparent background, no client border/shadow, and 110px shader-shadow
  padding. Normal launcher now uses the same material via the startup helper.
- Test output routing must happen in C++ before `LauncherWindow::loadRoot`
  finishes: set each window's QScreen and LayerShellQt::Window::screen.
  QML-only routing fell back to the physical display in this environment.
- New plugin built and loaded without bypassing ABI checks. Off-screen Wi-Fi
  shadow test over white at 20px below body: strength 1 gives 174/255,
  strength 0.2 gives 239/255, strength 0 gives 255/255. Separate Control Center
  surfaces were visually captured. Evidence: reference archive `11-linux-dropdowns`.
- Grouped presentation, notification/Sound backgrounds, additive glyph peaks
  156/246/255, and rendered mid-tint warp are captured in `16-linux-glass-proof`.
  Private test runtime does not exercise real PipeWire selection or physical input.

## Desktop-affinity implementation

`desktop-affinity.patch` adds a render pass after background wallpaper rendering,
before desktop icons and applications. `DesktopTint.inc` converts/downsamples the
live work buffer to encoded RGBA8 at 1/8 logical resolution; only complete
background damage is sampled, excluding stale foreground work-buffer pixels.
`DesktopTintMath.hpp` preserves SkyLight's integral-image indexing, fractional
area, six-bit quantization, and encoded Display-P3 Chameleon composition.
Wallpaper fades and neutral planes therefore share actual frames, not clocks.

Protocol v4 guarantees `apple-content`, `apple-footer`, and
`apple-sidebar-inactive`. Toolbar/base and sidebar glass body fills consume that
same window tone. The resident helper uses its own v3 symbol, preserving earlier
helper objects across hot reload. The capture pass is removed before unload;
GL samples and shader are released with AppleGlass state.

Apple layer surfaces accept `mac_neutral_rects` (up to 32 body-local rectangles:
`x`, `y`, `width`, `height`, `radius`, optional `hovered`) and optional
`mac_neutral_clip` (`x`, `y`, `width`, `height`). Neutral cards draw between glass
and client foreground. Geometry updates replace the previous neutral declaration
to bound storage while scrolling. Status advertises `desktopTint: true`;
QuickShell retains its CPU fallback until capability and geometry are ready.

Package checks include native oracle fixtures in `test-desktop-affinity.cpp` and
the protocol commit/lifetime test. Private GL rendering verified body/toolbar
tracking within 1/255 of the same-frame material during a wallpaper fade, plus
active/inactive sidebar, footer, and QuickShell cards. This does not establish
every HDR/multi-monitor edge case.

## Handoff

The single current status, reference archive index, safety constraints and
remaining desktop backlog are in
[`notes/MACOS_VISUAL_REFERENCE.md`](../../../../../notes/MACOS_VISUAL_REFERENCE.md).
That handoff distinguishes completed Spotlight/dropdown integration from
remaining material and nested-panel work. Temporary test sources are not deployed
dependencies; editable configuration is repo-backed.
