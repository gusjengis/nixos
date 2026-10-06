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

## Manual application and build

In a separate Hyprglass checkout at the pinned upstream revision:

```sh
git checkout --detach a54e7cd0232ca62a394aebebd553358dc6592652
for patch in experimental hdr-encoding linear-shadow refraction launcher-shape config-lifecycle layer-shadow surface-material portable-backend; do
    git apply --check "/etc/nixos/home/features/desktop/hyprland/glass/$patch.patch"
    git apply "/etc/nixos/home/features/desktop/hyprland/glass/$patch.patch"
done
```

Apply the complete patch once; do not separately reverse `b14733f` first.
Build the patched source against the matching fork, not generic Hyprland headers.
`package.nix` provides the reproducible build recipe: fixed upstream revision
and source hash, all nine patches in the order above, and an explicit matching
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
- A 110px inset reserves space for the shader's shadow. Negative radius chooses
  a capsule for the empty field and 23px continuous corners for expanded results.
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
  connectivity capsules, 140x140 media tile, and 292x64 slider platters at radius
  32 on one grouped surface. Transparent controller remains excluded from glass;
  fixed detail surface avoids changing namespace on an already-mapped window.
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

## Handoff

The single current status, reference archive index, safety constraints and
remaining desktop backlog are in
[`notes/MACOS_VISUAL_REFERENCE.md`](../../../../../notes/MACOS_VISUAL_REFERENCE.md).
That handoff distinguishes completed Spotlight/dropdown integration from
remaining material and nested-panel work. Temporary test sources are not deployed
dependencies; editable configuration is repo-backed.
