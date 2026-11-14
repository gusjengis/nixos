hl.monitor({
	output = "HDMI-A-1",
	mode = "3840x2160@30.00",
	position = "0x0",
	scale = 2.0,
})

-- Render X11 RDP clients at native resolution; Windows owns their UI scaling.
hl.config({
	xwayland = {
		force_zero_scaling = true,
	},
})
