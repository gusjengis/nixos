-- Loaded only on the conference PC. Disable bindings themselves rather than
-- swallowing Super and forwarding synthesized keys: Windows receives the real
-- press/release stream, including shortcuts unknown to this configuration.
local M = {}
local bindings = {}

local function remote_focused()
	local window = hl.get_active_window()
	-- Hyprland may retain the previous window after entering an empty workspace.
	if not window or not window.mapped or not window.workspace or not window.workspace.active then
		return false
	end
	local class = window and window.class:lower() or ""
	return class == "xfreerdp" or class == "wlfreerdp" or class:match("^rdp:") ~= nil
end

local function refresh()
	local remote = remote_focused()
	for _, pair in ipairs(bindings) do
		pair.normal:set_enabled(not remote)
		-- Physical key 580 stays usable across every focus/workspace transition.
		pair.remote:set_enabled(true)
	end
end

function M.bind(keys, dispatcher, flags)
	local remote_keys, count = keys:gsub("SUPER", "MOD3")
	-- Alt+F4 must close the remote application rather than the RDP connection.
	if keys == "ALT + F4" then
		remote_keys, count = "MOD3 + ALT + F4", 1
	end
	if count == 0 then
		return hl.bind(keys, dispatcher, flags)
	end
	local remote_flags = {}
	for key, value in pairs(flags or {}) do
		remote_flags[key] = value
	end
	-- Keep the local modifier usable even when a client inhibits shortcuts.
	remote_flags.dont_inhibit = true
	local normal = hl.bind(keys, dispatcher, flags)
	local remote = hl.bind(remote_keys, dispatcher, remote_flags)
	table.insert(bindings, { normal = normal, remote = remote })
	refresh()
	return normal
end

hl.on("window.active", refresh)
hl.on("window.class", refresh)
hl.on("workspace.active", refresh)
hl.on("workspace.special_active", refresh)
hl.on("config.reloaded", refresh)

return M
