# Chromium macOS dark appearance

`package.nix` patches the inner browser derivation, retaining the normal Nixpkgs
launcher, sandbox and Widevine packaging.

## Browser theme

Chromium 152 uses the shared Views/Skia color mixers for its macOS tabs and
toolbar. `chrome/browser/ui/color/mac/native_chrome_color_mixer_mac.cc` is an
empty hook: unlike Linux, it does not replace these colors with GTK/Qt values.
`macos-theme.patch` selects that macOS hook on Linux and starts the
profile on the default Chromium theme rather than its saved GTK/Qt theme.
The launcher forces dark mode. Caption buttons and their layout reservations
are removed.

The hook is now replaced with `native_chrome_color_mixer_macos_port.cc` and the
generated `macos_palette.inc`: a semantic-name-keyed snapshot of the reference
Mac's complete exposed UI/Chrome color inventory. Matching names override both
UI and browser colors; IDs missing in the reference retain their upstream recipe.
Light/dark and high-contrast captures are separate. Existing custom Chrome theme
suppliers still run afterward. This avoids relying on enum numbers across the
reference Chrome 156 and target Chromium 152 versions.

`macos-native-provider.patch` prevents saved or newly requested GTK/Qt theme
suppliers from taking over, hides the GTK/Qt appearance choices, selects the
captured system font size through a browser-private SF Pro text family, and
ports Mac typography height constants and Menlo selection. The font package
supplies the actual Menlo collection copied from the reference Mac.

### UI typography follow-up (2026-11-07)

The first deployment selected public `SF Pro` at 13px but left its optical axis
at the font's default, `opsz=28`. Live `NSFont.systemFont(ofSize:)` queries on the
reference Mac select `opsz=17` at sizes 12, 13, 14, 15, and 17pt, with normal
weight 400. Thus the mismatch was not solely monitor DPI or a different weight.

`fonts/package.nix` now partially instances Apple's existing public upright and
italic variable fonts at `opsz=17` and the default width/grade, retaining the
real weight axis. The private family `Chromium UI SF Pro` avoids changing other
applications or fonts chosen by web content. Its family-specific Fontconfig
rule enables antialiasing and disables hinting/autohinting/bitmap strikes.
The platform default re-queries render parameters after replacing GTK's face.

Chromium 152 enables WebUI omnibox results by default. That UI loads
`text_defaults_md.css`, whose Linux font stack prepended Roboto even after the
native Views font changed. Both WebUI font-default paths now use the private
family, covering suggestions and the shared browser-owned Settings/dialog UI.
Website CSS and generic family aliases are not patched. Monospace roles retain
Menlo. External Quickshell context menus use SF Pro at the same optical/weight
axes with native, unhinted text. All QuickShell context menus now use one
13-pixel SF Pro regular menu font, including desktop and tray menus.

Validation: both fonts built; upright/italic glyph outlines and advances at
weights 400/500/600/700 agree with the original `opsz=17` source within one font
unit. Fontconfig resolves real regular/bold weights with hinting off while
generic sans remains Noto Sans with its original settings. The Chromium patch
applies to the exact version; capture tests and external-menu socket/rendering
fixture pass. Final compiled-browser appearance still requires deployment and
visual acceptance. Linux Skia/FreeType does not reproduce CoreText edge coverage
exactly, and lower pixel density remains a separate limit.

Recheck generated font outlines (Python with fontTools):

```sh
python fonts/test_ui_font.py SOURCE_SF_PRO_FONT_DIRECTORY BUILT_UI_FONT_DIRECTORY
```

#### Current independent Omega build

The typography rebuild runs in `chromium-typography-build.service`, eight cores,
one local job, independent of the PC/SSH session. The old installed browser stays
active until this output is fetched and Home Manager is rebuilt.

- Package derivation: `/nix/store/ybwz69k5iyzh80hypsk5k7xb8bn3lp75-chromium-152.0.7977.75.drv`.
- Inner derivation: `/nix/store/miqwx574picq7s3clx35aivyk1699s2w-chromium-unwrapped-152.0.7977.75.drv`.
- Expected output: `/nix/store/zy2108xyrx2n2w12sy8d9v3823402va9-chromium-152.0.7977.75`.
- Output root: `/var/lib/chromium-typography-build/result`.
- Derivation root: `/nix/var/nix/gcroots/chromium-typography-build-derivation`.
- Built UI fonts: `/nix/store/z3n1w62fxwgl8rz6z3xhsncw7vax3i3a-chromium-ui-sf-pro-opsz17`.

```sh
ssh omega 'sudo systemctl show chromium-typography-build.service -p ActiveState -p Result -p ExecMainStatus; sudo journalctl -u chromium-typography-build.service -n 20 --no-pager -o cat'
# After successful completion:
sudo nix copy --no-check-sigs \
  --from 'ssh-ng://nixremote@omega.tail29bd65.ts.net?ssh-key=/home/gusjengis/.config/secrets/ssh/shared_ed25519' \
  /nix/store/zy2108xyrx2n2w12sy8d9v3823402va9-chromium-152.0.7977.75
rehome pc --flake path:/etc/nixos#pc
```

Verify `programs.chromium.package` still evaluates to that output before rehome.
Deployment must include the new UI font package and Fontconfig symlink, not only
the browser output. Fully restart Chromium, then inspect tabs, address bar,
suggestions (regular and bold), Settings and native/external menus. If the
corrected face still looks poor, restore the previous font consistently rather
than adding arbitrary weight to approximate CoreText.

This keeps Linux's Wayland window backend. It does not pretend that Cocoa or
AppKit can be linked on Linux, and it does not enable macOS build flags globally.

## Reference capture (2026-11-06)

The Mac runs macOS 27.0.1 (26A434), Google Chrome 156.0.8078.80. Its selected
profile uses `autogenerated_theme_id` with seed ARGB `FF000000`, not the default
macOS theme. A fresh default Mac profile also has a gray dark frame. The palette
used here intentionally captures that black autogenerated theme; baseline
captures are retained separately so user customization is not mislabeled as an
OS default. Only appearance preferences were inspected; profile contents were
not copied.

- `appkit-theme.json`: 128 semantic/public color getters per appearance, eight
  Aqua/vibrant/contrast variants, named color palettes, 13 font roles, nine
  font weights, four control-size metrics, and accessibility environment.
- `chrome-colors.json`: all 1,623 tokens returned by Chrome's
  `chrome://theme/colors.css?sets=ui,chrome`, across ten baseline/black-theme,
  light/dark, requested incognito, and high-contrast captures.
- `chromium-theme-sources.tar.gz`: versioned Chromium color/theme recipes,
  typography, layout/control/frame/material sources, and vector asset sources
  for both browser versions. Each version contains a hash/URL manifest. The
  upstream `components/vector_icons/google_chrome` entry is unavailable from
  the public raw source endpoint and is explicitly recorded, not synthesized.
- `extract-appkit-theme.m`, `extract-chrome-colors.py`, and
  `capture-chromium-theme-sources.py`: repeatable extraction tools. AppKit
  appearance overrides are local; Chrome captures use disposable profiles.
  Neither changes the user's appearance or Chrome profile.
- `generate-macos-palette.py`: deterministic RGBA-to-ARGB table generation.

The runtime color dump comes from a **headless WebContents color provider**.
It does not capture native window layer trees, composited material pixels, or
every possible browser-widget key. Requested incognito dumps currently equal
their baseline captures; they are not proof of incognito window-frame fidelity.
The provider leaves custom/incognito supplier behavior upstream rather than
inventing a distinct captured palette. Alternate accent seeds and accessibility
settings not exercised by these captures remain outside measured coverage.

Source recipes and assets are archived for auditing/reuse; archiving them does
not automatically port Cocoa painting, native materials, every control metric,
or newer Chrome 156 features into Chromium 152. SF Pro uses Linux rasterization.
The resulting build remains a Linux/Wayland browser with a captured Mac color
provider and selected native typography ports, not a complete Cocoa UI port.

Reproduce the generated palette and validate capture integrity:

```sh
python3 generate-macos-palette.py chrome-colors.json macos_palette.inc
PYTHONDONTWRITEBYTECODE=1 python3 test_macos_capture.py
```

## Context menus

The macOS menu runner delegates ordinary context menus to Cocoa. The patched
Linux factory delegates the same category of menu to Quickshell instead:

1. Chromium snapshots the menu model on its UI thread.
2. A worker connects to `$XDG_RUNTIME_DIR/chromium-quickshell-menu.sock` and sends
   one newline-terminated JSON object containing the items.
3. `ExternalContextMenus.qml` forwards it to `menus/ContextMenus.qml`, the shared
   factory for desktop, tray and browser context menus. `ContextMenuWindow.qml`
   and `ContextMenuRow.qml` own layout, input and compositor glass
   (`quickshell-menu`). Windows map only after their data and layout are ready.
4. The shell returns an integer action token, followed by a newline; `-1` is
   dismissal. Chromium validates the original model/index/command and enabled
    state before executing anything on its UI thread.

Snapshots include supplied icons as PNG data URLs (vector icons are rasterized
with the owning widget's color provider) and accelerator labels. Older browser
snapshots without these optional fields remain compatible.

`macos-titlecase.patch` enables GRIT's existing `use_titlecase` resource switch.
Upstream sets it to `is_mac` in `tools/grit/grit_args.gni`; the resource files
already author labels such as “New Tab to the Right” and “Open Link in New Tab”.
This selects the real macOS-style strings and translations rather than applying
a title-case filter to dynamic tab titles, filenames, URLs, or product names.

`page-context-menu.patch` also routes `ToolkitDelegateViews` through the
model-backed factory. Upstream page menus instead construct a prebuilt Views
tree, which bypasses that factory. Page, link, image, selection and editable
context menus therefore use the same bridge as tab-bar context menus. The
delegate tolerates the absence of a Views menu host; model show/close callbacks
still notify the web contents through the bridge. Website-drawn DOM menus
(such as YouTube's custom video menu) never reach this delegate.

Connection lifetime belongs to the menu runner. Cancellation, owner destruction
or shell disconnection dismisses the menu. If Quickshell is unavailable, or a
menu contains custom button rows/actionable submenus, the normal Chromium menu
runner handles it. Drag/drop and nested menus retain their existing runner.

Submenus open on hover as separate glass surfaces aligned with their parent row,
flip left at screen edges, and share keyboard navigation and dismissal. This bridge
does not redirect Chrome's custom application-menu Views or HTML menus drawn
inside websites.

## Verification and deployment

```sh
quickshell -p /etc/nixos/home/features/desktop/quickshell/test_external_context_menus.qml
nix build --no-link --cores 8 --max-jobs 1 path:/etc/nixos#homeConfigurations.pc.config.programs.chromium.package
rehome pc --flake path:/etc/nixos#pc
```

The QML fixture checks the shared menu renderer, disabled/check states,
mnemonics, keyboard navigation, submenu selection, dismissal and an actual Unix
socket request/response. The package compiles the bridge object first to catch
Chromium API changes before the full browser build.

A source-patched browser requires a full Chromium build. After deployment,
restart Chromium completely to load its new executable; the launcher cannot
replace an already-running browser process.

### Independent Omega build / installation handoff (2026-11-06)

The requested provider build now runs as a root system service **on Omega**,
independent of PC, SSH connections, and OpenCode. The former PC user service
`chromium-macos-install.service` was stopped. Installation is intentionally left
for a later agent after the remote build finishes.

- Service: `chromium-macos-build.service` on `omega.tail29bd65.ts.net`.
- Build: eight cores, one local job, `--keep-failed`, no remote builders.
- Pinned package derivation:
  `/nix/store/iwdj801c5jhcsvvmqc2j5zpss8rx3nl1-chromium-152.0.7977.75.drv`.
- Expected package output:
  `/nix/store/63l7s96mj3hp77ijd40xs1mfpjfjgbbw-chromium-152.0.7977.75`.
- Inner browser derivation:
  `/nix/store/f0k82slgl74n21z8d3ys8v8minkza9jf-chromium-unwrapped-152.0.7977.75.drv`.
- Omega GC root `chromium-macos-build-derivation` pins the derivation closure.
  Successful output is rooted at `/var/lib/chromium-macos-build/result`.
- This is a transient **Omega** service: PC may reboot freely; rebooting Omega
  interrupts it. If necessary, restart the exact derivation using the command
  below. A failed build does not install anything on PC.

Monitor from PC:

```sh
ssh omega 'sudo journalctl -fu chromium-macos-build.service -n 20 -o cat'
```

Later agent: confirm service success and that the rooted executable runs:

```sh
ssh omega 'sudo systemctl show chromium-macos-build.service -p ActiveState -p Result -p ExecMainStatus; sudo readlink -f /var/lib/chromium-macos-build/result; sudo /var/lib/chromium-macos-build/result/bin/chromium --version'
```

Fetch from the explicitly trusted fleet SSH endpoint into PC's system store:

```sh
sudo nix copy --no-check-sigs \
  --from 'ssh-ng://nixremote@omega.tail29bd65.ts.net?ssh-key=/home/gusjengis/.config/secrets/ssh/shared_ed25519' \
  /nix/store/63l7s96mj3hp77ijd40xs1mfpjfjgbbw-chromium-152.0.7977.75
rehome pc --flake path:/etc/nixos#pc
```

Home Manager adds its command-line flags through a separate launcher derivation,
so compare the installed launcher with `programs.chromium.finalPackage`, not
`programs.chromium.package`. If unrelated long builds block deployment, inspect
`/tmp/opencode/rehome-chromium/flake.nix`: its locked snapshot retains the Handy,
Strata, and contextctl packages installed when this job was requested. Refresh
that deployment wrapper to current intended configuration before using it if
other configuration work has since been applied. Keep the browser source inputs
unchanged to reuse this compiled artifact. Verify launcher, restart Chromium,
then verify the actual appearance and standard/page context menus.

To recreate the Omega job if its host has rebooted (first confirm no duplicate
build is already running):

```sh
ssh omega 'sudo systemd-run --unit=chromium-macos-build --property=Type=exec --property=StateDirectory=chromium-macos-build --property=Nice=10 --property=TimeoutStartSec=infinity --setenv=PATH=/run/current-system/sw/bin /run/current-system/sw/bin/nix build --store daemon --out-link /var/lib/chromium-macos-build/result --cores 8 --max-jobs 1 --builders "" --keep-failed -L /nix/store/iwdj801c5jhcsvvmqc2j5zpss8rx3nl1-chromium-152.0.7977.75.drv^out'
```
