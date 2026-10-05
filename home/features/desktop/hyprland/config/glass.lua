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
local namespaces = "vicinae,quickshell-menu,quickshell-panel,quickshell-cc-pill,quickshell-cc-tile,quickshell-cc-detail,quickshell-notification-card"
local grouped = glass.mac_rects_supported and glass.mac_rects_supported()
if grouped then
	namespaces = namespaces .. ",quickshell-cc-group"
end
glass.config({
	enabled = false,
	layers = { enabled = true, namespaces = namespaces },
	mac = { tint = tint },
})
glass.layer("vicinae", { mac_inset = 110, mac_radius = -1, mac_placeholder_additive = true })
-- QuickShell dropdowns (bar/components/GuardedPopupWindow.qml). Inset must
-- equal Theme.glassShadowPadding; radii match Theme.menuRadius/panelRadius.
glass.layer("quickshell-menu", { mac_inset = 80, mac_radius = 13, mac_shadow = 0.2, mac_outline = 0.2 })
glass.layer("quickshell-panel", { mac_inset = 80, mac_radius = 22, mac_shadow = 0.2, mac_outline = 0.2 })
glass.layer("quickshell-cc-pill", { mac_inset = 80, mac_radius = 32, mac_shadow = 0.08, mac_outline = 0.2 })
glass.layer("quickshell-cc-tile", { mac_inset = 80, mac_radius = 32, mac_shadow = 0.08, mac_outline = 0.2 })
glass.layer("quickshell-notification-card", { mac_inset = 80, mac_radius = 22, mac_shadow = 0.2, mac_outline = 0.2, mac_tangential = false })
glass.layer("quickshell-cc-detail", { mac_inset = 80, mac_radius = 13, mac_shadow = 0.2, mac_outline = 0.2, mac_profile = "control", mac_tangential = false })
if grouped then
	glass.layer("quickshell-cc-group", {
		mac_inset = 80,
		mac_shadow = 0.08,
		mac_outline = 0.2,
		mac_profile = "control",
		mac_tangential = false,
		mac_rects = {
			{ 0, 0, 140, 64, 32 },
			{ 0, 76, 140, 64, 32 },
			{ 152, 0, 140, 140, 32 },
			{ 0, 152, 292, 64, 32 },
			{ 0, 228, 292, 64, 32 },
		},
	})
end
