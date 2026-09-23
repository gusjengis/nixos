hl.monitor({
	output = "HDMI-A-1",
	mode = "3840x2160@120.00",
	scale = 1.0,
	position = "0x0",
})

local internalMonitor = {
	output = "eDP-1",
	mode = "3456x2234@120.00",
	scale = 2.0,
	position = "3840x1043",
}
local monitorModes = require("monitor-modes")
local internalOutput = internalMonitor.output

local function setInternalDisplay(enabled)
	if enabled then
		hl.monitor(internalMonitor)
	else
		hl.monitor({ output = internalOutput, disabled = true })
	end
end

setInternalDisplay(true)

hl.window_rule({
	name = "internal-notch-fullscreen",
	match = { workspace = "m[" .. internalOutput .. "]", fullscreen_state_internal = 1, fullscreen_state_client = 2 },
	border_size = 0,
	rounding = 0,
	no_shadow = true,
})

-- The client has to believe it is fullscreen and the compositor has to be
-- filling the screen with it. A client can report itself fullscreen while the
-- compositor shows it normally, which is not a fullscreen. Any non-zero
-- compositor state counts, because the window is briefly true fullscreen before
-- the translation to maximized lands.
local function isTranslatedFullscreen(window)
	return window.fullscreen > 0 and window.fullscreen_client == 2
end

-- Derived from live state rather than accumulated from events, so a window that
-- closes or leaves the panel while fullscreen cannot strand the margin rules.
local function syncInternalFullscreen(ignoredAddress)
	local workspace = hl.get_active_workspace(internalOutput)
	local active = false

	if workspace then
		for _, window in ipairs(hl.get_workspace_windows(workspace)) do
			if window.address ~= ignoredAddress and isTranslatedFullscreen(window) then
				active = true
				break
			end
		end
	end

	monitorModes.set_fullscreen(internalOutput, active)
end

-- Keep client fullscreen semantics while sizing fullscreen windows to the
-- layer-shell work area below the notch. External monitors remain true
-- fullscreen because this conversion only runs for the internal panel.
hl.on("window.fullscreen", function(window)
	local monitor = window.monitor

	if monitor and monitor.name == internalOutput and window.fullscreen == 2 then
		hl.dispatch(hl.dsp.window.fullscreen_state({
			internal = 1,
			client = 2,
			action = "set",
			window = "address:" .. window.address,
		}))
	end

	syncInternalFullscreen()
end)

hl.on("window.close", function(window)
	syncInternalFullscreen(window.address)
end)

hl.on("window.move_to_workspace", function()
	syncInternalFullscreen()
end)

hl.on("workspace.active", function()
	syncInternalFullscreen()
end)

hl.bind("switch:on:Apple SMC power/lid events", function()
	setInternalDisplay(false)
end, { locked = true })

-- Re-enabling a disabled output requires applying the complete monitor config.
hl.bind("switch:off:Apple SMC power/lid events", hl.dsp.exec_cmd("hyprctl reload"), { locked = true })

local function lidIsClosed()
	local command =
		"/run/current-system/sw/bin/busctl get-property org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager LidClosed"
	local process = io.popen(command)
	if not process then
		return false
	end
	local state = process:read("*a")
	process:close()
	return state:match("true") ~= nil
end

-- display-recovery also reloads Hyprland. Reconcile after its scheduled monitor
-- rules apply so those reloads cannot bring the panel back while the lid is shut.
hl.timer(function()
	if lidIsClosed() then
		setInternalDisplay(false)
	end
end, { timeout = 500, type = "oneshot" })

-- Manual fallback for the DCP HDMI link teardown that display-recovery.nix
-- normally handles on its own. Forces the output down and back up, which is
-- the only thing that makes DCP run a fresh modeset once it has dropped its
-- timings. Host-specific, so it lives here rather than in keybinds.lua;
-- hyprland.lua requires this file after keybinds, so hl.bind is available.
hl.bind("SUPER + CTRL + ALT + SHIFT + D", hl.dsp.exec_cmd("display-recovery --once HDMI-A-1"), {
	description = "Recover HDMI output",
})

monitorModes.configure({
	["HDMI-A-1"] = {
		enabled = true,
		margins = { top = 200, right = 747, bottom = 200, left = 747 },
	},
	["eDP-1"] = {
		enabled = false,
		margins = { top = 100, right = 278, bottom = 100, left = 278 },
	},
})
