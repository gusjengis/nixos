local vars = require("platform-variables")
local features = require("desktop-features")
require("appearance")
require("autostart")
require("workspaces")
require("keybinds")

local file_present, monitors = pcall(require, "monitors")
if not file_present then
	hl.monitor({
		output = "",
		mode = "preferred",
		position = "auto",
		scale = "auto",
	})
end

hl.config({
	cursor = {
		inactive_timeout = 3,
	},

	misc = {
		force_default_wallpaper = 0,
		disable_hyprland_logo = true, -- If true disables the random hyprland logo / anime girl background. :(
		disable_splash_rendering = true, -- If true disables the splash screen.
		focus_on_activate = false,
		initial_workspace_tracking = 0,
	},
})

hl.config({
	input = {
		kb_layout = "us",
		kb_variant = "",
		kb_model = "",
		kb_options = "",
		kb_rules = "",
		kb_file = features.rdp_keymap or "",

		repeat_delay = 190,
		repeat_rate = 50,

		follow_mouse = 1,

		sensitivity = 0, -- -1.0 - 1.0, 0 means no modification.

		touchpad = {
			natural_scroll = false,
			tap_to_click = false,
			tap_and_drag = true,
		},
	},
})

hl.config({
	dwindle = {
		preserve_split = true, -- You probably want this
	},
})

hl.config({
	master = {
		new_status = "master",
	},
})

hl.config({
	scrolling = {
		fullscreen_on_one_column = true,
	},
})
local swipe_distance = 0
hl.gesture({
	fingers = 3,
	direction = "horizontal",
	action = {
		start = function()
			swipe_distance = 0
		end,
		update = function(event)
			swipe_distance = swipe_distance + event.delta.x
		end,
		finish = function(event)
			if features.contexts and not event.cancelled and math.abs(swipe_distance) >= 80 then
				require("sessions").cycle(swipe_distance < 0 and 1 or -1)
			end
		end,
	},
})
