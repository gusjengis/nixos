hl.monitor({
	output = "HDMI-A-1",
	mode = "3840x2160@120.00",
	scale = 1.0,
	position = "0x0",
})

local internalMonitor = {
	output = "eDP-1",
	mode = "3456x2160@120.00",
	scale = 2.0,
	position = "3840x1080",
}

local function setInternalDisplay(enabled)
	if enabled then
		hl.monitor(internalMonitor)
	else
		hl.monitor({ output = "eDP-1", disabled = true })
	end
end

setInternalDisplay(true)

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
