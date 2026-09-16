hl.monitor({
	output = "HDMI-A-1",
	mode = "3840x2160@144.00",
	scale = 1.0,
	position = "0x0",
})

hl.monitor({
	output = "eDP-1",
	mode = "3456x2160@120.00",
	scale = 2.0,
	position = "3840x1080",
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
