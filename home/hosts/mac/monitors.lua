hl.monitor({
	output = "HDMI-A-1",
	mode = "3840x2160@120.00",
	scale = 1.0,
	position = "0x0",
})

hl.monitor({
	output = "eDP-1",
	mode = "3456x2160@120.00",
	scale = 2.0,
	position = "3840x1080",
})

-- Manual fallback for the DCP HDMI link teardown that display-recovery.nix
-- normally handles on its own. Forces the output down and back up, which is
-- the only thing that makes DCP run a fresh modeset once it has dropped its
-- timings. Host-specific, so it lives here rather than in keybinds.lua;
-- hyprland.lua requires this file after keybinds, so hl.bind is available.
hl.bind("SUPER + CTRL + ALT + SHIFT + D", hl.dsp.exec_cmd("display-recovery --once HDMI-A-1"), {
	description = "Recover HDMI output",
})

require("monitor-modes").configure({
	["HDMI-A-1"] = {
		enabled = true,
		margins = { top = 200, right = 747, bottom = 200, left = 747 },
	},
	["eDP-1"] = {
		enabled = false,
		margins = { top = 100, right = 278, bottom = 100, left = 278 },
	},
})
