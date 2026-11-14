# Shared context menus

Every QuickShell context menu enters `ContextMenus.open(request)`:

- Desktop background/files: `DesktopSurface.qml` supplies action entries.
- System tray: `bar/components/TrayMenu.qml` supplies a live D-Bus menu handle.
- Chromium: `ExternalContextMenus.qml` adapts socket snapshots and command tokens.
- Dock icons and Trash: `DockMenu.qml` supplies macOS Dock items and a `callout`.

`ContextMenus.qml` owns the only active root and its lifetime.
`ContextMenuWindow.qml` renders each level, loads D-Bus children through
`QsMenuOpener`, handles hover/keyboard navigation, and maintains one linear
submenu branch and one focus grab. `ContextMenuRow.qml` is the only row renderer.
`GuardedPopupWindow.qml` supplies the existing `quickshell-menu` layer surface;
Hyprglass applies its Apple menu material and shadow. Callers do not choose fonts,
draw rows, or create menu windows.

## Contract

`open({ owner, entries, source, screen, position, anchorItem, keyboard,
activate, cancel })` replaces the current menu and returns its pending root.
Use normalized `entries` or a live `source` handle. `position` is screen-local;
`anchorItem` is for a menu-bar anchor. `callout: {x, bottom}` (Dock) places the
body so its pointer tip is at `x`, 27 pt from the body's left edge (right edge
near the screen edge), with the body ending at `bottom`; the window then uses the
`quickshell-dock-menu[-end]` glass namespace, whose compositor shape adds the
measured 10 pt pointer, and sizes to its content. `close(owner)` dismisses only that owner's
menu. Activation hides the full chain before dispatching one action; cancellation
is separate and emitted once.

Entries support `text`, `enabled`, `isSeparator`, `buttonType`, `checkState`,
`icon` (a Qt image URL), `shortcut`, `hasChildren`, and `children`. Adapters can
retain extra action data. Mnemonics are removed by the adapter or for D-Bus
labels; literal ampersands and dynamic names are preserved.

## Reference and first-frame readiness

The reference Mac (macOS 27.0.1) reports `NSFont.menuFont(ofSize: 0)` as
13-point regular system text with optical size 17. Finder accessibility geometry
confirms 24-point rows, 11-point separators and 5-point body padding. Submenu
bodies overlap their parent's edge by 5 points and align their first row with
the spawning row. `Theme.menuFont` pins those axes and uses -0.25 pixel tracking
to approximate CoreText's system tracking; four reference advances are checked
within 0.9 pixel. Platform rasterization can differ.

Enabled label ink is opaque white in both selection states. Highlighting changes
the background only; isolated production-label captures are byte-identical.
Checks use a shared state column; each supplied icon has its own leading slot.

Call `present()`, not `visible = true`. A window waits for nonempty menu data
and the glass-capability probe, flushes hidden delegates/layout, then maps at its
complete dimensions. This applies to roots and children. The existing Hyprland
`quickshell-dropdown-no-animation` rule disables transitions. Do not restore the
empty-window-then-resize path: it exposed tiny surfaces and stretched glyph
buffers during asynchronous D-Bus loading.

## Verification

Run these fixtures under the active Wayland session:

```sh
qs -p /etc/nixos/home/features/desktop/quickshell/test_context_menus.qml
qs -p /etc/nixos/home/features/desktop/quickshell/test_external_context_menus.qml
qs -p /etc/nixos/home/features/desktop/quickshell/test_desktop.qml
qs -p /etc/nixos/home/features/desktop/quickshell/test_menu_text.qml
qs -p /etc/nixos/home/features/desktop/quickshell/test_dock_menu.qml
nix-shell -p python3Packages.dbus-next --run 'python /etc/nixos/home/features/desktop/quickshell/test_dbus_context_menus.py'
```

Fixtures cover real tray loading, hidden preparation, native font advances,
hover/nested/sibling branches, placement/edge flipping, keyboard navigation,
single action/cancel delivery, actual Unix requests, desktop action dispatch,
and isolated text captures under `/tmp/opencode`.
The D-Bus server fixture deliberately delays layout replies, opens two real
submenu handles on hover, and verifies the final `clicked` event reaches its
exported menu item exactly once.

`qs ipc call contextMenus snapshot` reports the live chain;
`qs ipc call contextMenus dismiss` closes it. A November 9 recording of Steam's
actual tray menu at 144 fps showed no menu through frame 373 and all final glyphs
in frame 374, with no intermediate surface size or opacity.
