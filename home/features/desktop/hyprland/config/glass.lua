local dataHome = os.getenv("XDG_DATA_HOME") or (os.getenv("HOME") .. "/.local/share")
local library = dataHome .. "/hyprglass/libhyprglass.so"
local file = io.open(library, "rb")
if not file then
	return
end
file:close()

if not hl.plugin.hyprglass then
	return
end

local configHome = os.getenv("XDG_CONFIG_HOME") or (os.getenv("HOME") .. "/.config")
local tintFile = io.open(configHome .. "/quickshell/theme/glass-tint", "r")
local tint = 1
if tintFile then
	tint = tonumber(tintFile:read("*a")) or 1
	tintFile:close()
end
tint = math.max(0, math.min(1, tint))

local glass = hl.plugin.hyprglass
local namespaces = "vicinae,quickshell-menu,quickshell-panel,quickshell-session-picker,quickshell-cc-pill,quickshell-cc-tile,quickshell-cc-detail,quickshell-notification-card,quickshell-in-progress,quickshell-capture,quickshell-dock,quickshell-dock-tip,quickshell-dock-menu,quickshell-dock-menu-end"
local grouped = glass.mac_rects_supported and glass.mac_rects_supported()
if grouped then
	namespaces = namespaces .. ",quickshell-cc-group"
end
glass.config({
	enabled = false,
	layers = { enabled = true, namespaces = namespaces },
	mac = { tint = tint },
})
-- mac_apple selects a ported QuartzCore glass_background preset with Apple's own
-- decoded settings (MacOS Theme session, 27-real-glass). Builds without it ignore
-- the key and keep the fitted material described by the other mac_* keys.
-- apple-menu = DesignLibrary Configuration.regular, size medium, glass diffusion 1
-- (Spotlight and menu-bar menus: 32/86 interior over black/white).
-- Keep the 57px compact bar's half-height radius when results expand.
glass.layer("vicinae", { mac_inset = 110, mac_radius = 28.5, mac_placeholder_additive = true, mac_apple = "apple-menu" })
-- QuickShell dropdowns (bar/components/GuardedPopupWindow.qml). Inset must
-- equal Theme.glassShadowPadding; radii match Theme.menuRadius/panelRadius.
glass.layer("quickshell-menu", { mac_inset = 80, mac_radius = 13, mac_shadow = 0.2, mac_outline = 0.2, mac_apple = "apple-menu" })
-- Dock right-click menus (Dock.qml): the menu body plus a measured 10 pt pointer
-- whose tip is 27 pt from the body's left edge, or from its right edge when
-- the menu would leave the screen. The glass box includes the pointer.
glass.layer("quickshell-dock-menu", { mac_inset = 80, mac_radius = 13, mac_shadow = 0.2, mac_outline = 0.2, mac_apple = "apple-menu", mac_material = { callout = { 27, 10 } } })
glass.layer("quickshell-dock-menu-end", { mac_inset = 80, mac_radius = 13, mac_shadow = 0.2, mac_outline = 0.2, mac_apple = "apple-menu", mac_material = { callout = { -27, 10 } } })
glass.layer("quickshell-usage", { mac_inset = 80, mac_radius = 13, mac_shadow = 0.2, mac_outline = 0.2, mac_apple = "apple-menu" })
glass.layer("quickshell-panel", { mac_inset = 80, mac_radius = 22, mac_shadow = 0.2, mac_outline = 0.2, mac_apple = "apple-menu" })
-- SessionPicker.qml uses the Spotlight/menu material and matching shadow inset.
glass.layer("quickshell-session-picker", { mac_inset = 80, mac_radius = 22, mac_shadow = 0.2, mac_outline = 0.2, mac_apple = "apple-menu" })
-- InProgressWidget.qml reserves the same 80px shadow padding around its card.
glass.layer("quickshell-in-progress", { mac_inset = 80, mac_radius = 24, mac_shadow = 0.2, mac_outline = 0.2, mac_apple = "apple-menu" })
-- Capture.qml reserves the same shadow inset around its rounded dictation card.
glass.layer("quickshell-capture", { mac_inset = 80, mac_radius = 24, mac_shadow = 0.2, mac_outline = 0.2, mac_apple = "apple-widgets" })
-- Dock.qml body. mac_apple = Configuration.dock, size medium, adaptive(false),
-- glass diffusion 1 plus its glass-highlight rim. The fitted fallback below is
-- fitted to the macOS 27 Dock (tint 1, dark)
-- on 3840x2160@1x: interior tone over a gray ramp, chroma from solid red/blue,
-- blur from checker/grid/stripes, rim/outline from 1px edge profiles. The Dock
-- has no drop shadow; its dark outline is only on the left/right sides.
-- Running dots and the separator are additive gray-124 ink (plus-lighter).
-- Evidence: MacOS Theme session, 26-dock/.
local dockRim = { 0.353, 0.835, 0.715, 0.333, 2.47, 0.04, 13.7 }
glass.layer("quickshell-dock", {
	mac_inset = 80,
	mac_radius = 29,
	mac_shadow = 0,
	mac_outline = 0.62,
	mac_placeholder_additive = true,
	mac_apple = "apple-dock",
	mac_material = {
		lut = { 0.0471, 0.1020, 0.1529, 0.2000, 0.2510, 0.2941, 0.3412, 0.3804, 0.4235, 0.4627, 0.5020, 0.5373, 0.5686, 0.6039, 0.6314, 0.6627, 0.6824 },
		chroma = 1.16,
		blur = { 8.89, 17.46, 0.85 },
		rim = dockRim,
		outline_side_power = 2,
	},
})
-- DockTooltip.qml: one capsule + rounded-pointer silhouette, measured against
-- 26-dock/mac/hover-{black,gray,white}. Pointer shares the body material.
glass.layer("quickshell-dock-tip", {
	mac_inset = 80,
	mac_radius = 13,
	mac_shadow = 0,
	mac_outline = 0.72,
	mac_material = {
		dock_tooltip = true,
		lut = { 0.1294, 0.1578, 0.1849, 0.2105, 0.2347, 0.2576, 0.2790, 0.2990, 0.3176, 0.3348, 0.3507, 0.3651, 0.3781, 0.3897, 0.3999, 0.4087, 0.4144 },
		chroma = 1.0,
		blur = { 8.89, 17.46, 0.85 },
		rim = dockRim,
		outline_side_power = 2,
	},
})
-- Captured directly from running macOS 27 system apps, dark / diffusion 1.
-- These two presets retain the extracted full-tint inputs. Separate system
-- backdrop shadows are a later pass; no compensating tone fit is applied here.
glass.layer("quickshell-cc-pill", { mac_inset = 80, mac_radius = 32, mac_shadow = 0.08, mac_outline = 0.2, mac_apple = "apple-control-center" })
glass.layer("quickshell-cc-tile", { mac_inset = 80, mac_radius = 32, mac_shadow = 0.08, mac_outline = 0.2, mac_apple = "apple-control-center" })
glass.layer("quickshell-notification-card", { mac_inset = 80, mac_radius = 20, mac_shadow = 0.2, mac_outline = 0.2, mac_tangential = false, mac_apple = "apple-notification" })
glass.layer("quickshell-cc-detail", { mac_inset = 80, mac_radius = 13, mac_shadow = 0.2, mac_outline = 0.2, mac_profile = "control", mac_tangential = false, mac_apple = "apple-control-center" })
if grouped then
	glass.layer("quickshell-cc-group", {
		mac_inset = 80,
		mac_shadow = 0.08,
		mac_outline = 0.2,
		mac_profile = "control",
		mac_tangential = false,
		mac_apple = "apple-control-center",
		mac_rects = {
			{ 0, 0, 140, 64, 32 },
			{ 0, 76, 140, 64, 32 },
			{ 152, 0, 140, 140, 32 },
			{ 0, 152, 292, 64, 32 },
			{ 0, 228, 292, 64, 32 },
			{ 0, 304, 292, 64, 32 },
		},
	})
end
