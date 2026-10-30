local directory = assert(arg[0]:match("^(.*[/])"))
package.path = directory .. "?.lua;" .. package.path
local active, callbacks, binds = nil, {}, {}
hl = {
	get_active_window = function() return active end,
	on = function(event, callback) callbacks[event] = callback end,
	bind = function(keys, action, flags)
		local binding = { enabled = true, action = action, flags = flags or {} }
		function binding:set_enabled(value) self.enabled = value end
		binds[keys] = binding
		return binding
	end,
}
local register = require("rdp-keybinds").bind
local count = 0
local function action() count = count + 1 end
local flags = { mouse = true }
register("SUPER + 2", action)
register("SUPER + mouse:272", action, flags)
register("ALT + F4", action)
register("XF86AudioMute", action)
assert(binds["SUPER + 2"].enabled and binds["MOD3 + 2"].enabled)
assert(not flags.dont_inhibit, "Do not mutate caller flags")
assert(binds["MOD3 + mouse:272"].flags.mouse)
assert(binds["MOD3 + 2"].flags.dont_inhibit)
for _, class in ipairs({ "xfreerdp", "wlfreerdp", "RDP:server" }) do
	active = { class = class, mapped = true, workspace = { active = true } }
	callbacks["window.active"]()
	assert(not binds["SUPER + 2"].enabled and binds["MOD3 + 2"].enabled)
	assert(not binds["ALT + F4"].enabled and binds["MOD3 + ALT + F4"].enabled)
	assert(binds["XF86AudioMute"].enabled)
	binds["MOD3 + 2"].action()
end
assert(count == 3, "Direct RDP-to-RDP workspace bindings must stay usable")
active = { class = "kitty" }
callbacks["window.active"]()
assert(binds["SUPER + 2"].enabled and binds["MOD3 + 2"].enabled)
active = nil
callbacks["window.active"]()
assert(binds["SUPER + 2"].enabled and binds["MOD3 + 2"].enabled)
active = { class = "xfreerdp", mapped = true, workspace = { active = true } }
callbacks["config.reloaded"]()
assert(binds["MOD3 + 2"].enabled and not binds["SUPER + 2"].enabled)
active.workspace.active = false
callbacks["workspace.active"]()
assert(binds["SUPER + 2"].enabled and binds["MOD3 + 2"].enabled,
	"Stale RDP focus on empty workspace must not disable Super")
active.workspace.active = true
callbacks["workspace.active"]()
assert(not binds["SUPER + 2"].enabled)
active.mapped = false
callbacks["window.active"]()
assert(binds["SUPER + 2"].enabled, "Unmapped RDP must not disable Super")
active.class = "kitty"
callbacks["window.class"]()
assert(binds["SUPER + 2"].enabled and binds["MOD3 + 2"].enabled)
print("PASS: always-on Mod3; Super only outside RDP; focus/class/reload transitions, capture override, mouse flags, Alt+F4")
