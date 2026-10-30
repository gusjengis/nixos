local directory = assert(arg[0]:match("^(.*[/])"), "Use a path to this test")
package.path = directory .. "?.lua;" .. package.path
package.loaded["desktop-features"] = { contexts = false, personal = false, development = false }
package.loaded["platform-variables"] = { terminal = "kitty", browser = "chromium", fileManager = "thunar" }
package.preload.sessions = function()
	error("Disabled contexts must not load session manager")
end
package.preload["context-terminals"] = function()
	error("Disabled contexts must not load terminal restoration")
end

local binds, startup, launched, dispatches = {}, {}, {}, {}
local selected
local function dispatchers(path)
	return setmetatable({}, {
		__index = function(_, key)
			return dispatchers(path .. "." .. key)
		end,
		__call = function(_, value)
			return { kind = path, value = value }
		end,
	})
end
hl = {
	dsp = dispatchers("dsp"),
	bind = function(keys, action)
		binds[keys] = action
	end,
	window_rule = function() end,
	on = function(event, callback)
		startup[event] = callback
	end,
	exec_cmd = function(command)
		launched[#launched + 1] = command
	end,
	dispatch = function(action)
		dispatches[#dispatches + 1] = action
	end,
	get_active_monitor = function()
		return {
			set_workspace = function(_, value)
				selected = value
			end,
		}
	end,
}
require("workspaces")
require("keybinds")
require("autostart")
assert(not binds["SUPER + Z"] and not binds["SUPER + SHIFT + Z"])
assert(not binds["SUPER + SHIFT + K"] and not binds["code:202"])
assert(binds["SUPER + F"].value == "thunar")
binds["SUPER + 3"]()
assert(selected == "3", "Plain workspace shortcut failed")
binds["SUPER + SHIFT + 3"]()
assert(dispatches[1].kind == "dsp.window.move" and dispatches[1].value.workspace == "3")
assert(binds["SUPER + CTRL + ALT + SHIFT + R"].value == "systemctl reboot")
assert(binds["SUPER + CTRL + ALT + SHIFT + S"].value == "systemctl poweroff")
startup["hyprland.start"]()
for _, command in ipairs(launched) do
	assert(not command:find("context", 1, true), command)
	assert(not command:find("mailspring", 1, true), command)
	assert(not command:find("handy", 1, true), command)
	assert(not command:find("kdeconnect", 1, true), command)
end
print("PASS: ordinary workspaces, direct file launch, restart, and no context/personal autostarts")
