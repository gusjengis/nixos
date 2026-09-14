hl.monitor({
	output = "eDP-1",
	mode = "1920x1080@60.00800",
	position = "0x0",
	scale = 1.0,
})

require("monitor-modes").configure({
	["eDP-1"] = {
		enabled = true,
		single_window_margins = { top = 134, right = 352, bottom = 135, left = 352 },
		multiple_window_margins = 10,
	},
})
