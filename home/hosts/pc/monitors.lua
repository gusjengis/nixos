hl.monitor({
	output = "HDMI-A-1",
	mode = "3840x2160@120.00",
	position = "0x0",
	scale = 1.0,

	bitdepth = 10,
	cm = "hdr",
	sdr_max_luminance = 350,
	sdr_min_luminance = 0,
})

require("monitor-modes").configure({
	["HDMI-A-1"] = {
		enabled = true,
		margins = { top = 200, right = 747, bottom = 200, left = 747 },
	},
})
