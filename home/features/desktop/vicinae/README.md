# Spotlight presentation

The package applies the Spotlight patches in `default.nix`; editable settings
and theme remain linked from this directory.

## Launch workspace tracking

Hyprland uses `misc.initial_workspace_tracking = 2`. The workspace-tracking
patch synchronously dispatches each application activation through Hyprland,
which assigns a fresh token on Enter/activation rather than when the launcher
opens. Delayed windows and inherited child processes follow that workspace;
moving the primary window updates its children's destination. Applications
already running before tracking was enabled need restarting to inherit a token.

Arguments and working directories are shell-quoted independently; Lua long-string
delimiters are chosen to avoid collisions. Non-Hyprland desktops retain the
original QProcess path. A failed compositor dispatch reports launch failure.
Entries without an explicit working directory start in the user's home directory.
Inheriting the launcher's directory can break sandboxed applications: Steam's
FHS environment hides `/etc/nixos`, so Bubblewrap cannot chdir there.

Live acceptance check (briefly switches workspaces and restarts Vicinae):

```sh
python home/features/desktop/vicinae/test_workspace_tracking.py
```

This exercises the installed application's activation path with a 12-second
delayed window, different launcher-open/activation/mapping workspaces, a child
spawned after moving its parent, fresh tokens on subsequent activations, and
argument/working-directory quoting. Probe windows and desktop entries are
removed afterward and the original workspace is restored.

## Scale-1 geometry

Reference: the session archive's
`08-spotlight-glass/query-s__photo-current__tint1.png`.

| Element | Target |
| --- | --- |
| Popup width | 640 px |
| Search field including border | 57 px |
| Highlight horizontal bounds | x=10 through x=630, 620 px wide |
| Root result height / normal pitch | 57 px |
| Visible app artwork | 37 × 37 px |
| Visible artwork left edge | x=18 |
| Title left edge | x=71 |
| Visible artwork-to-title gap | 16 px |
| Trailing search-field artwork | 26 × 26 px |

Icon canvases are 39 px in results and 28 px in the search field. The installed
app artwork is normalized to about 94% of its canvas; neither location adds
ViciImage safety margins. Measure visible artwork, not the Item rectangle.

Result highlights use continuous-curvature corners in `SourceBlendRect`, with
the same exponent/shape family as the existing outer glass compositor. A local
fit to the unobstructed Mac selection corner gives an 18.5 px nominal radius
with exponent 2.238. The fit's quadratic-backdrop assumption is not proof of
complete material parity. The outer compositor already uses continuous corners.

Completion stays highlighted while navigating. With an empty query it previews
the entire selected title and its icon; moving the caret into actual query text
suppresses the preview. Subtitles are hidden in shared result delegates and
the specialized clipboard/store lists. Root type labels remain selected-only.

Title ink stays opaque white across selection. Title origins are integer-aligned;
the existing 4× mipmapped text layers remain in use. No selected-only font weight
compensation is applied. Shared list rows default to the same 57 px presentation.
Matching three identical reference labels favors SF Pro 18 px Medium, with a
1 px upward optical correction. The reference/Qt coverage comparison is recorded
with the captures; it does not eliminate platform rasterization differences.

## Focused regression check

Run with the pinned, unpacked Vicinae source directory:

```sh
nix-shell -p 'python3.withPackages (p: [ p.pyside6 ])' --run \
  'python home/features/desktop/vicinae/test_spotlight.py /path/to/vicinae-source'
```

The check applies the production patch chain to temporary source fixtures,
executes the actual text/layout and completion QML offscreen, and checks
selection/accessory/subtitle transitions, byte-identical glyph pixels, empty
query previews, caret editing, long-title clipping, and QML warnings. Native
image/shader measurements additionally require real launcher captures.

The session archive's `22-spotlight-parity/` contains actual isolated launcher
captures, measurements, and reproduction helpers. Xvfb fallback-material captures
verify foreground geometry and behavior; they do not verify the live Wayland
glass material, HDR appearance, or complete popup pixel parity.
