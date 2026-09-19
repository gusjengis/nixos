local vars = require("platform-variables")
local home = os.getenv("HOME")
local repo = os.getenv("NIXOS_CONFIG_ROOT") or "/etc/nixos"

local function bind(keys, dispatcher, description, flags)
	flags = flags or {}
	flags.description = description
	hl.bind(keys, dispatcher, flags)
end

local function preserve_quickshell_focus(command)
	return "qs ipc call focusGuard suspend; " .. command .. "; qs ipc call focusGuard resume"
end

bind("SUPER + SPACE", hl.dsp.exec_cmd("qs ipc call launcher toggle"), "App Launcher")
bind("SUPER + CTRL + SPACE", hl.dsp.exec_cmd("qs ipc call launcher remote"), "Remote Launcher")
bind("SUPER + SHIFT + T", hl.dsp.exec_cmd("qs ipc call launcher tools"), "Tools Launcher")
bind("SUPER + Q", hl.dsp.exec_cmd(vars.terminal), "Launch Terminal")
bind("SUPER + B", hl.dsp.exec_cmd(vars.browser), "Launch Browser")
bind("ALT + F4", hl.dsp.window.close(), "Close Program")
bind("SUPER + F11", hl.dsp.window.fullscreen(), "Fullscreen")
bind("SUPER + F", hl.dsp.exec_cmd(vars.fileManager), "Launch File Manager")
bind("SUPER + V", hl.dsp.window.float(), "Toggle Floating")
bind("SUPER + W", hl.dsp.exec_cmd("qs ipc call wallpaper toggle"), "Wallpaper Picker")
bind("SUPER + R", hl.dsp.exec_cmd("qs ipc call bar toggle"), "Toggle Status Bar")
bind(
	"SUPER + SHIFT + N",
	hl.dsp.exec_cmd("bash " .. repo .. "/home/features/desktop/wallpaper/next-wallpaper.sh"),
	"Next Wallpaper"
)
bind(
	"SUPER + SHIFT + P",
	hl.dsp.exec_cmd("bash " .. repo .. "/home/features/desktop/wallpaper/previous-wallpaper.sh"),
	"Previous Wallpaper"
)
bind("SUPER + J", hl.dsp.layout("togglesplit"), "Rotate Split")

bind("code:202", hl.dsp.exec_cmd("handy --toggle-transcription"), "Dictate")
hl.bind("code:202", hl.dsp.exec_cmd("handy --toggle-transcription"), { release = true })
bind("XF86AudioMicMute", hl.dsp.exec_cmd("handy --toggle-transcription"), "Dictate")
hl.bind("XF86AudioMicMute", hl.dsp.exec_cmd("handy --toggle-transcription"), { release = true })

bind(
	"SUPER + SHIFT + S",
	hl.dsp.exec_cmd(preserve_quickshell_focus("take-screenshot output " .. home .. "/Pictures/Screenshots")),
	"Screenshot"
)
bind(
	"SUPER + SHIFT + A",
	hl.dsp.exec_cmd(preserve_quickshell_focus("take-screenshot region " .. home .. "/Pictures/Screenshots")),
	"Screenshot Area"
)
bind(
	"SUPER + SHIFT + W",
	hl.dsp.exec_cmd(preserve_quickshell_focus("take-screenshot window " .. home .. "/Pictures/Screenshots")),
	"Screenshot Window"
)

for _, direction in ipairs({ "left", "right", "up", "down" }) do
	bind(
		"SUPER + " .. direction,
		hl.dsp.focus({ direction = direction }),
		"Focus " .. direction:gsub("^%l", string.upper)
	)
end

for _, direction in ipairs({ "left", "right", "up", "down" }) do
	bind(
		"SUPER + SHIFT + " .. direction,
		hl.dsp.window.swap({ direction = direction }),
		"Swap Window " .. direction:gsub("^%l", string.upper)
	)
end

-- hl.bind("SUPER + SHIFT + P", hl.dsp.window.pin({ action = "enable" }))

local function monitor_workspace(workspace)
	local monitor = hl.get_active_monitor()
	local name = monitor.name .. ":" .. workspace
	local legacy = hl.get_workspace(workspace)

	if legacy and legacy.monitor == monitor then
		hl.dispatch(hl.dsp.workspace.rename({ workspace = legacy, name = name }))
	end

	return "name:" .. name
end

for workspace = 1, 10 do
	local key = workspace % 10
	bind("SUPER + " .. key, function()
		hl.dispatch(hl.dsp.focus({ workspace = monitor_workspace(workspace), on_current_monitor = true }))
	end, "Workspace " .. workspace)
	bind("SUPER + SHIFT + " .. key, function()
		hl.dispatch(hl.dsp.window.move({ workspace = monitor_workspace(workspace) }))
	end, "Move to Workspace " .. workspace)
end

bind("SUPER + CTRL + ALT + SHIFT + E", hl.dsp.exit(), "Exit Hyprland")
bind("SUPER + CTRL + ALT + SHIFT + S", hl.dsp.exec_cmd("alga power off; systemctl poweroff"), "Shutdown")
bind("SUPER + CTRL + ALT + SHIFT + R", hl.dsp.exec_cmd("systemctl reboot"), "Restart")

bind("SUPER + mouse:272", hl.dsp.window.drag(), "Move Window", { mouse = true })
bind("SUPER + mouse:273", hl.dsp.window.resize(), "Resize Window", { mouse = true })

bind(
	"XF86AudioRaiseVolume",
	hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"),
	"Hidden",
	{ locked = true, repeating = true }
)
bind(
	"XF86AudioLowerVolume",
	hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"),
	"Hidden",
	{ locked = true, repeating = true }
)
bind(
	"XF86AudioMute",
	hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"),
	"Hidden",
	{ locked = true, repeating = true }
)
bind("XF86AudioNext", hl.dsp.exec_cmd("playerctl next"), "Hidden", { locked = true })
bind("XF86AudioPause", hl.dsp.exec_cmd("playerctl play-pause"), "Hidden", { locked = true })
bind("XF86AudioPlay", hl.dsp.exec_cmd("playerctl play-pause"), "Hidden", { locked = true })
bind("XF86AudioPrev", hl.dsp.exec_cmd("playerctl previous"), "Hidden", { locked = true })

bind(
	"SUPER + H",
	hl.dsp.exec_cmd(
		"pkill wl-kbptr || ("
			.. preserve_quickshell_focus("wl-kbptr -c " .. repo .. "/home/features/desktop/cursor/wl-kbptr.conf")
			.. ")"
	),
	"Hop"
)

hl.window_rule({
	name = "suppress-maximize-events",
	match = { class = ".*" },
	suppress_event = "maximize",
})

hl.window_rule({
	name = "fix-xwayland-drags",
	match = {
		class = "^$",
		title = "^$",
		xwayland = true,
		float = true,
		fullscreen = false,
		pin = false,
	},
	no_focus = true,
})

hl.window_rule({
	name = "hide-xwayland-video-bridge",
	match = { class = "^(xwaylandvideobridge)$" },
	opacity = "0.0 override",
	no_anim = true,
	no_initial_focus = true,
	max_size = { 1, 1 },
	no_blur = true,
	no_focus = true,
})

hl.window_rule({
	name = "move-hyprland-run",
	match = { class = "hyprland-run" },
	move = "20 monitor_h-120",
	float = true,
})
