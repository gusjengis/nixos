-- Run from repo root with an isolated XDG_RUNTIME_DIR/signature; see README.md.
local module_path = "home/features/desktop/hyprland/config/sessions/init.lua"
local base = assert(os.getenv("XDG_RUNTIME_DIR"))
	.. "/hyprland-sessions-"
	.. assert(os.getenv("HYPRLAND_INSTANCE_SIGNATURE"))
assert(os.getenv("HYPRLAND_INSTANCE_SIGNATURE"):match("^test%-"), "Use an isolated test signature")
os.remove(base .. ".lua")
os.remove(base .. ".json")

local events, workspaces, monitors, launches, windows, timers, rules = {}, {}, {}, {}, {}, {}, {}
setmetatable(windows, {
	__newindex = function(registry, key, window)
		if window then
			setmetatable(window, {
				__index = function(value, property)
					if property == "monitor" and not value.detached then
						return value.workspace and value.workspace.monitor
					end
				end,
			})
		end
		rawset(registry, key, window)
	end,
})
local close_requests, cleanup_timers = {}, {}
local focused, focused_window
local function emit(event, ...)
	for _, callback in ipairs(events[event] or {}) do
		callback(...)
	end
	if event == "config.unload" then
		cleanup_timers = {}
	end
end
local function resolve(name, output)
	name = name:gsub("^name:", "")
	if not workspaces[name] then
		workspaces[name] = {
			addressable_name = name,
			name = name,
			monitor = output,
			special = name:match("^special:") ~= nil,
			windows = 0,
		}
	end
	return workspaces[name]
end
local function add_monitor(name)
	local output = { name = name, enabled = true }
	function output:set_workspace(name)
		local previous = self.active_workspace
		self.active_workspace = resolve(name, self)
		self.active_workspace.monitor = self
		for _, window in pairs(windows) do
			if window.pinned and window.workspace == previous then
				window.detached = nil
				previous.windows = previous.windows - 1
				window.workspace = self.active_workspace
				window.workspace.windows = window.workspace.windows + 1
				emit("window.move_to_workspace", window, window.workspace)
			end
		end
		emit("workspace.active", self.active_workspace)
	end
	function output:set_special_workspace(name)
		-- Native monitor API accepts a bare name, not a workspace address.
		if not name then
			self.special_closes = (self.special_closes or 0) + 1
		end
		name = name and ("special:" .. name)
		if name then
			for _, other in ipairs(monitors) do
				if other.active_special_workspace and other.active_special_workspace.addressable_name == name then
					other.active_special_workspace = nil
				end
			end
		end
		self.active_special_workspace = name and resolve(name, self) or nil
		if self.active_special_workspace then
			self.active_special_workspace.monitor = self
		end
		emit("workspace.special_active", self.active_special_workspace, self)
	end
	monitors[#monitors + 1] = output
	return output
end
local left = add_monitor("DP-1")
local right = add_monitor("HDMI-A-1")
focused = left
left:set_workspace("DP-1:1")
right:set_workspace("2")
right.active_workspace.id = 2
left:set_special_workspace("terminal")
left.active_special_workspace.windows = 1
windows["address:0x1"] = { address = "0x1", workspace = left.active_special_workspace }
resolve("DP-1:7", left).windows = 2
resolve("special:music", left).windows = 1
windows["address:0x4"] = { address = "0x4", workspace = workspaces["special:music"] }

hl = {
	get_monitors = function()
		return monitors
	end,
	get_monitor = function(name)
		for _, output in ipairs(monitors) do
			if output.name == name then
				return output
			end
		end
	end,
	get_active_monitor = function()
		return focused
	end,
	get_workspaces = function()
		local result = {}
		for _, workspace in pairs(workspaces) do
			result[#result + 1] = workspace
		end
		return result
	end,
	get_workspace = function(name)
		return workspaces[name:gsub("^name:", "")]
	end,
	get_window = function(name)
		return windows[name]
	end,
	get_active_window = function()
		return windows[focused_window]
	end,
	get_windows = function(query)
		assert(not query or type(query.workspace) == "table", "Migration must query an existing workspace object")
		local result = {}
		for _, window in pairs(windows) do
			if not query or window.workspace == query.workspace then
				result[#result + 1] = window
			end
		end
		return result
	end,
	on = function(event, callback)
		events[event] = events[event] or {}
		table.insert(events[event], callback)
	end,
	timer = function(callback, config)
		if config.timeout == 25 then
			cleanup_timers[#cleanup_timers + 1] = callback
		elseif config.timeout < 1000 then
			callback()
		else
			timers[#timers + 1] = callback
		end
	end,
	window_rule = function(config)
		local rule = { config = config, enabled = true }
		function rule:set_enabled(enabled)
			self.enabled = enabled
		end
		rules[#rules + 1] = rule
		return rule
	end,
	exec_cmd = function(command, rules)
		launches[#launches + 1] = { command, rules.workspace }
	end,
	dsp = {
		focus = function(args)
			return { focus = args }
		end,
		window = {
			pin = function(args)
				return { pin = args }
			end,
			close = function(args)
				return { close = args.window }
			end,
			move = function(args)
				return { move = args }
			end,
		},
	},
	dispatch = function(action)
		if action.pin then
			local window = assert(windows[action.pin.window])
			if not window.monitor then
				return { ok = false, error = "Window has no monitor" }
			end
			local enabled = action.pin.action == "enable"
			if not not window.pinned ~= enabled then
				window.pinned = enabled
				local output = window.workspace.monitor
				window.workspace.windows = window.workspace.windows - 1
				window.workspace = output.active_workspace
				window.workspace.windows = window.workspace.windows + 1
				emit("window.move_to_workspace", window, window.workspace)
				emit("window.pin", window)
			end
		elseif action.close then
			assert(windows[action.close], "Close must target an existing window")
			close_requests[#close_requests + 1] = action.close
		elseif action.focus then
			if action.focus.monitor then
				focused = hl.get_monitor(action.focus.monitor)
			elseif action.focus.window then
				focused_window = action.focus.window
				local workspace = windows[action.focus.window].workspace
				if workspace.special then
					workspace.monitor:set_special_workspace(workspace.addressable_name:sub(9))
				else
					workspace.monitor:set_workspace(workspace.addressable_name)
				end
			end
		else
			if action.move.window then
				assert(action.move.follow == false, "migration must not follow windows or steal focus")
			end
			local window = windows[action.move.window or "address:0x1"]
			local target = resolve(action.move.workspace, focused)
			if window.workspace ~= target then
				window.workspace.windows = window.workspace.windows - 1
				window.workspace = target
				window.detached = nil
				window.workspace.windows = window.workspace.windows + 1
			end
		end
		return { ok = true }
	end,
}
local config = {
	launch_matches = { browser = { class = "chromium-browser" } },
	specials = {
		terminal = function(id)
			return "terminal " .. id
		end,
		browser = "browser --new-window",
		music = "music-player",
		podcast = "podcast-player",
	},
}
local sessions = dofile(module_path)
sessions.setup(config)
assert(sessions.state().active == "s1")
assert(sessions.state().workspaces["DP-1"][7] == "DP-1:7", "adopt without moving windows")
assert(sessions.special_name("terminal") == "special:terminal")
sessions.toggle_special("terminal", "DP-1")
assert(left.active_special_workspace == nil)
sessions.toggle_special("terminal", "DP-1")
assert(
	left.active_special_workspace.addressable_name == "special:terminal",
	"adopted scratchpad must remain accessible"
)
assert(#launches == 0, "existing scratchpad must not launch duplicate application")
local first = sessions.state()
local second = sessions.create("Research")
assert(second == "s2" and sessions.state().active == second)
assert(left.active_special_workspace == nil, "outgoing special must hide")
assert(left.active_workspace.addressable_name ~= first.workspaces["DP-1"][1])
assert(right.active_workspace.addressable_name ~= first.workspaces["HDMI-A-1"][2])
local hidden = sessions.state("s1")
assert(hidden.active == second, "inspecting hidden session must preserve active identity")
assert(hidden.workspaces["DP-1"][7] == "DP-1:7", "hidden state must expose original workspace addresses")
assert(hidden.specials.terminal == "special:terminal", "hidden state must preserve adopted special address")
assert(left.active_workspace.addressable_name == sessions.state().workspaces["DP-1"][1], "inspection must not change monitor view")
sessions.select_workspace(7, "DP-1")
sessions.select_workspace(4, "HDMI-A-1")
sessions.show_special("terminal", "HDMI-A-1")
assert(#launches == 1 and launches[1][1] == "terminal s2")
assert(right.active_special_workspace.addressable_name == sessions.special_name("terminal"))
assert(not workspaces["special:" .. sessions.special_name("terminal")], "special prefix must not be doubled")
sessions.show_special("terminal", "HDMI-A-1")
assert(#launches == 1, "pending launch must not duplicate")
right.active_special_workspace.windows = 1
windows["address:0x2"] = { address = "0x2", workspace = right.active_special_workspace }
emit("window.open", windows["address:0x2"])
assert(focused_window == "address:0x2", "first mapped scratchpad window must receive keyboard focus")
local second_terminal = sessions.special_name("terminal")
sessions.previous()
assert(sessions.state().active == "s1")
assert(left.active_workspace.addressable_name == "DP-1:1")
assert(right.active_workspace.addressable_name == "2")
assert(left.active_special_workspace.addressable_name == "special:terminal")
assert(right.active_special_workspace == nil)
sessions.previous()
assert(left.active_workspace.addressable_name == sessions.state().workspaces["DP-1"][7])
assert(right.active_workspace.addressable_name == sessions.state().workspaces["HDMI-A-1"][4])
assert(right.active_special_workspace.addressable_name == second_terminal)
assert(focused == right, "switch must preserve focused output")
sessions.toggle_special("terminal", "HDMI-A-1")
assert(right.active_special_workspace == nil)
sessions.toggle_special("terminal", "DP-1")
assert(left.active_special_workspace.addressable_name == second_terminal)
assert(#launches == 1)
sessions.launch_special("browser", "browser URL", sessions.special_name("browser"))
assert(rules[1].enabled and rules[1].config.no_initial_focus)
assert(rules[1].config.workspace == sessions.special_name("browser") .. " silent")
assert(not pcall(sessions.launch_special, "browser", "browser URL"), "pending launch must not race placement rules")
local browser = resolve(sessions.special_name("browser"), left)
browser.windows = 1
emit("window.open", { workspace = browser })
assert(focused_window == "address:0x2", "hidden launch must not take keyboard focus")
assert(not rules[1].enabled, "placement rule must retire after window maps")
assert(not pcall(sessions.launch_special, "browser", "browser URL", "special:wrong"))
sessions.select_workspace(10, "DP-1")
sessions.cycle(1)
assert(left.active_workspace.addressable_name == sessions.state().workspaces["DP-1"][1])
sessions.cycle(-1)
assert(left.active_workspace.addressable_name == sessions.state().workspaces["DP-1"][10])
assert(not pcall(sessions.select_workspace, 11))
assert(not pcall(sessions.select_workspace, 1, "missing"))
assert(not pcall(sessions.create, "Research"))
assert(not pcall(sessions.create, "\n"))
sessions.rename(second, 'Research "quoted" \\ name')
assert(sessions.state().sessions[2].name == 'Research "quoted" \\ name')

-- Simulate successful config reload: interpreter-local callbacks disappear.
browser.windows = 0
sessions.show_special("browser", "DP-1")
local launch_count = #launches
emit("config.unload")
events = {}
timers, rules = {}, {}
sessions = dofile(module_path)
sessions.setup(config)
assert(sessions.state().active == "s2")
assert(#launches == launch_count, "reload must not respawn pending application")
assert(#rules == 1 and rules[1].enabled, "reload must restore pending browser placement")
sessions.previous()
assert(sessions.state().workspaces["DP-1"][7] == "DP-1:7", "sparse adoption survives serialization")
assert(
	not pcall(sessions.launch_special, "browser", "browser URL"),
	"reload must preserve cross-session launch serialization"
)
browser.windows = 1
emit("window.open", { address = "0x3", workspace = browser })
assert(focused_window == "address:0x2", "late launch must not focus after session switch")
assert(not rules[1].enabled)
sessions.focus_window("address:0x1")
assert(sessions.state().active == "s1")
assert(left.active_special_workspace.addressable_name == "special:terminal")

-- External focus into another session must switch all outputs coherently.
sessions.switch("s2")
right:set_workspace("2")
assert(sessions.state().active == "s1")
assert(left.active_workspace.addressable_name == "DP-1:1")
sessions.move_window(3, "DP-1")
assert(windows["address:0x1"].workspace.addressable_name == sessions.state().workspaces["DP-1"][3])

local third = add_monitor("eDP-1")
emit("monitor.added", third)
assert(third.active_workspace.addressable_name == sessions.state().workspaces["eDP-1"][1])
table.remove(monitors, 2)
right.enabled = false
emit("monitor.removed", right)
sessions.switch("s2")
right:set_workspace("2")
assert(sessions.state().active == "s2", "disconnect replacement must not switch session")
right.enabled = true
table.insert(monitors, right)
emit("monitor.added", right)
assert(right.active_workspace.addressable_name == sessions.state().workspaces["HDMI-A-1"][4])
assert(sessions.state().sessions[2].name == 'Research "quoted" \\ name')

-- Pins follow workspaces within their session, but never follow another session.
local pin_home = sessions.state().active
local pin_windows = {}
for index, output in ipairs({ left, right }) do
	local key = "address:0xpin" .. index
	local window = { address = "0xpin" .. index, workspace = output.active_workspace, floating = true }
	windows[key] = window
	window.workspace.windows = window.workspace.windows + 1
	hl.dispatch(hl.dsp.window.pin({ window = key, action = "enable" }))
	pin_windows[index] = window
end

-- Output teardown can leave a mapped pin without a window monitor, even though
-- its workspace has already returned to the connected display.
pin_windows[1].detached = true
assert(pin_windows[1].monitor == nil and pin_windows[1].workspace.monitor == left)
local reconnected = sessions.create("Reconnect regression")
assert(sessions.state().active == reconnected, "monitorless pin must not block creation or switching")
assert(not pin_windows[1].detached and not pin_windows[1].pinned, "native workspace move repairs and parks orphan pin")
sessions.close(reconnected)
assert(sessions.state().active == pin_home and pin_windows[1].pinned and pin_windows[2].pinned)

local before_failure = sessions.state()
local prior_views = {}
for _, output in ipairs(monitors) do
	prior_views[output.name] = output.active_workspace.addressable_name
end
local set_workspace = right.set_workspace
local fail_once = true
right.set_workspace = function(output, name)
	if fail_once then
		fail_once = false
		error("Injected output activation failure")
	end
	return set_workspace(output, name)
end
assert(not pcall(sessions.create, "Retry after failure"))
right.set_workspace = set_workspace
assert(
	sessions.state().active == before_failure.active and #sessions.state().sessions == #before_failure.sessions,
	"failed creation must not reserve an invisible session"
)
for _, output in ipairs(monitors) do
	assert(
		output.active_workspace.addressable_name == prior_views[output.name],
		"failed switch must restore prior views"
	)
end
assert(pin_windows[1].pinned and pin_windows[2].pinned, "rollback must restore pin state")
local retried = sessions.create("Retry after failure")
sessions.close(retried)
assert(sessions.state().active == pin_home)

for _, output in ipairs(monitors) do
	output.enabled = false
end
assert(not pcall(sessions.create, "No display"))
assert(
	sessions.state().active == pin_home and #sessions.state().sessions == #before_failure.sessions,
	"display outage must not leave ghost sessions"
)
emit("monitor.removed", right)
for _, output in ipairs(monitors) do
	output.enabled = true
end
emit("monitor.added", right)
local after_outage = sessions.create("No display")
sessions.close(after_outage)
assert(pin_windows[1].pinned and pin_windows[2].pinned, "reconnected outputs keep original pin intent")

sessions.select_workspace(6, "DP-1")
assert(
	pin_windows[1].pinned and pin_windows[1].workspace == left.active_workspace,
	"pins follow local workspace changes"
)
local parked_workspace = pin_windows[1].workspace
sessions.switch("s1")
for _, window in ipairs(pin_windows) do
	assert(
		not window.pinned and window.workspace ~= window.workspace.monitor.active_workspace,
		"outgoing pins must hide"
	)
end
-- Inactive pin ownership and intent survive a configuration reload.
emit("config.unload")
events, timers, rules, cleanup_timers = {}, {}, {}, {}
sessions = dofile(module_path)
sessions.setup(config)
emit("config.reloaded")
sessions.focus_window("address:0xpin1")
assert(sessions.state().active == pin_home and pin_windows[1].pinned and pin_windows[2].pinned)
assert(pin_windows[1].workspace == parked_workspace, "return restores pins on their monitor's remembered workspace")
-- An external compositor switch migrates native pins before notifying the backend.
left:set_workspace("DP-1:1")
assert(sessions.state().active == "s1")
assert(
	not pin_windows[1].pinned and pin_windows[1].workspace == parked_workspace,
	"external switch must undo pin migration"
)
sessions.switch(pin_home)
assert(pin_windows[1].pinned and pin_windows[2].pinned, "both monitors restore their pins")
hl.dispatch(hl.dsp.window.pin({ window = "address:0xpin1", action = "disable" }))
sessions.switch("s1")
sessions.switch(pin_home)
assert(not pin_windows[1].pinned, "explicit unpin must not be restored")
pin_windows[2].floating, pin_windows[2].pinned = false, false
sessions.switch("s1")
sessions.switch(pin_home)
assert(not pin_windows[2].pinned, "native tiling clears logical pin intent")
for index, window in ipairs(pin_windows) do
	window.workspace.windows = window.workspace.windows - 1
	windows["address:0xpin" .. index] = nil
end

-- Rule-created pins on hidden sessions are parked without stealing visibility.
local rule_workspace = resolve(sessions.state().workspaces["DP-1"][6], left)
sessions.switch("s1")
local ruled = { address = "0xpinrule", workspace = rule_workspace, pinned = true, floating = true }
windows["address:0xpinrule"] = ruled
rule_workspace.windows = rule_workspace.windows + 1
emit("window.open", ruled)
assert(not ruled.pinned and ruled.workspace == rule_workspace, "hidden rule-created pin stays in its session")
sessions.switch(pin_home)
assert(ruled.pinned, "rule-created pin restores on session return")
ruled.workspace.windows = ruled.workspace.windows - 1
windows["address:0xpinrule"] = nil

-- Promote existing per-session players to a shared scratchpad on reload.
local other_music = sessions.special_name("music")
assert(other_music ~= "special:music")
resolve(other_music, right).windows = 1
windows["address:0x5"] = { address = "0x5", workspace = workspaces[other_music] }
sessions.show_special("podcast", "DP-1")
local pending_podcast_second = sessions.special_name("podcast")
sessions.switch("s1")
sessions.show_special("podcast", "DP-1")
local pending_podcast_first = sessions.special_name("podcast")
sessions.switch("s2")
emit("config.unload")
config.global_specials = { music = true, radio = true, podcast = true }
config.specials.radio = "radio-player"
events, timers, rules = {}, {}, {}
sessions = dofile(module_path)
sessions.setup(config)
assert(sessions.special_name("music") == "special:music", "reuse existing populated player workspace")
assert(windows["address:0x4"].workspace == workspaces["special:music"], "original player stays in place")
assert(windows["address:0x5"].workspace == workspaces["special:music"], "consolidate additional player windows")
assert(windows["address:0x1"].workspace.addressable_name ~= "special:music", "do not move unrelated windows")
local podcast_launches = #launches
assert(
	sessions.special_name("podcast") == pending_podcast_first,
	"reuse pending launch destination when no player has mapped"
)
sessions.show_special("podcast", "DP-1")
assert(#launches == podcast_launches, "promoting pending players must not spawn another copy")
workspaces[pending_podcast_second].windows = 1
windows["address:0x7"] = { address = "0x7", workspace = workspaces[pending_podcast_second] }
emit("window.open", windows["address:0x7"])
assert(
	windows["address:0x7"].workspace.addressable_name == pending_podcast_first,
	"consolidate late arrivals after promotion"
)
local before_music = #launches
sessions.show_special("music", "HDMI-A-1")
local closes = right.special_closes
sessions.switch("s1")
assert(right.special_closes == closes, "global workspace must not be hidden and recreated on switch")
assert(sessions.special_name("music") == "special:music")
assert(sessions.state().specials.music == "special:music", "bar snapshot must expose global address in every session")
assert(right.active_special_workspace.addressable_name == "special:music", "visible global must survive session switch")
sessions.toggle_special("music", "HDMI-A-1")
sessions.switch("s2")
assert(not right.active_special_workspace, "hidden global must not resurrect from another session")
assert(sessions.special_name("terminal") == second_terminal, "other scratchpads remain session-local")
sessions.focus_window("address:0x4")
assert(sessions.state().active == "s2", "focusing global player must not switch sessions")
assert(#launches == before_music, "global player must not relaunch on session switch")
sessions.show_special("music", "DP-1")
assert(left.active_special_workspace.addressable_name == "special:music")
assert(not right.active_special_workspace, "global scratchpad moves between monitors without copying")
sessions.show_special("radio", "DP-1")
assert(#launches == before_music + 1, "empty global launches once")
local radio = sessions.special_name("radio")
sessions.switch("s1")
sessions.show_special("radio", "DP-1")
assert(#launches == before_music + 1, "pending global launch is shared across sessions")
workspaces[radio].windows = 1
windows["address:0x6"] = { address = "0x6", workspace = workspaces[radio] }
emit("window.open", windows["address:0x6"])
assert(focused_window == "address:0x6", "visible global launch receives focus even after session switch")
emit("config.unload")
events, timers, rules = {}, {}, {}
-- Compositor may clear current display state while applying output config.
for _, output in ipairs(monitors) do
	output.active_special_workspace = nil
end
sessions = dofile(module_path)
sessions.setup(config)
emit("config.reloaded")
assert(left.active_special_workspace.addressable_name == radio, "reload must restore saved global visibility")
assert(sessions.special_name("music") == "special:music", "global address survives reload")
sessions.switch("s2")
assert(left.active_special_workspace.addressable_name == radio, "global visibility survives reload and switching")
emit("config.unload")
config.global_specials = { radio = true, podcast = true }
events, timers, rules = {}, {}, {}
sessions = dofile(module_path)
sessions.setup(config)
assert(sessions.special_name("music") == "special:music", "demoted player belongs to current session")
sessions.switch("s1")
assert(sessions.special_name("music") ~= "special:music", "demoted player is no longer global")

local function drain_cleanup()
	while #cleanup_timers > 0 do
		table.remove(cleanup_timers, 1)()
	end
end
local function complete_close(window_address)
	local window = assert(windows[window_address])
	emit("window.close", window)
	window.workspace.windows = window.workspace.windows - 1
	windows[window_address] = nil
	drain_cleanup()
end
local function find_session(id)
	for _, item in ipairs(sessions.state().sessions) do
		if item.id == id then
			return item
		end
	end
end
local original = sessions.state().active
local empty = sessions.create("Disposable")
sessions.kill(empty)
drain_cleanup()
assert(not find_session(empty) and sessions.state().active == original, "empty active session should delete and return")
local inactive_empty = sessions.create("Disposable inactive")
sessions.switch(original)
sessions.kill(inactive_empty)
drain_cleanup()
assert(
	not find_session(inactive_empty) and sessions.state().active == original,
	"deleting empty inactive session should not switch"
)
assert(#close_requests == 0, "empty session deletion must not close global players")
sessions.kill("s2")
drain_cleanup()
assert(
	find_session("s2").closing and find_session("s2").window_count == 3,
	"closing session must retain save-dialog access"
)
assert(sessions.state().active == "s2", "show populated closing session")
assert(#close_requests == 3, "close local numbered/special windows, not globals or other sessions")
for _, window_address in ipairs(close_requests) do
	assert(window_address ~= "address:0x1" and window_address ~= "address:0x6" and window_address ~= "address:0x7")
end
assert(not pcall(sessions.launch_special, "terminal", "terminal"), "closing session must not launch another local app")
assert(sessions.kill == sessions.close, "previous kill command remains an alias for close")
local dialog_workspace = windows["address:0x4"].workspace
dialog_workspace.windows = dialog_workspace.windows + 1
windows["address:0xb"] = { address = "0xb", workspace = dialog_workspace }
emit("window.open", windows["address:0xb"])
assert(#close_requests == 3, "new save dialogs must never receive automatic close requests")
assert(find_session("s2").window_count == 4, "save dialog remains accessible inside closing session")
complete_close("address:0xb")
complete_close("address:0x2")
complete_close("address:0x5")
assert(find_session("s2").closing and find_session("s2").window_count == 1, "cancelled save dialog must retain session")
emit("config.unload")
events, timers, rules, cleanup_timers = {}, {}, {}, {}
sessions = dofile(module_path)
sessions.setup(config)
emit("config.reloaded")
assert(find_session("s2").closing, "closing state survives reload without forcing dialogs")
sessions.kill("s2")
assert(close_requests[#close_requests] == "address:0x4", "retry close only remaining window")
complete_close("address:0x4")
assert(not find_session("s2") and sessions.state().active == "s1", "delete only when windows actually exit")
assert(
	windows["address:0x1"] and windows["address:0x6"] and windows["address:0x7"],
	"other-session and global windows survive"
)
assert(sessions.state().previous ~= "s2", "previous pointer must not reference deleted session")
assert(not pcall(sessions.kill, "does-not-exist"))
local starting = sessions.create("Starting")
sessions.show_special("terminal", "DP-1")
local starting_workspace = sessions.special_name("terminal")
sessions.kill(starting)
drain_cleanup()
assert(find_session(starting).closing, "pending launch must keep closing session registered")
local previous_focus = focused_window
local previous_closes = #close_requests
workspaces[starting_workspace].windows = 1
windows["address:0x9"] = { address = "0x9", workspace = workspaces[starting_workspace] }
emit("window.open", windows["address:0x9"])
assert(#close_requests == previous_closes, "late arrivals must be preserved until another explicit close request")
assert(focused_window == previous_focus, "late arrival into closing session must not take focus")
windows["address:0xc"] = { address = "0xc", workspace = workspaces[starting_workspace], pinned = true }
emit("window.open", windows["address:0xc"])
assert(#close_requests == previous_closes, "pinned arrivals must not receive close requests")
sessions.kill(starting)
local retry_closes = {}
for index = previous_closes + 1, #close_requests do
	retry_closes[close_requests[index]] = true
end
assert(
	retry_closes["address:0x9"] and retry_closes["address:0xc"],
	"explicit retry closes local windows including pins"
)
complete_close("address:0x9")
assert(find_session(starting).closing, "pinned save confirmations keep their owning session accessible")
complete_close("address:0xc")
assert(not find_session(starting), "session is removed after late window exits")
workspaces[starting_workspace].windows = 1
windows["address:0xa"] = { address = "0xa", workspace = workspaces[starting_workspace] }
emit("window.open", windows["address:0xa"])
assert(close_requests[#close_requests] ~= "address:0xa", "very late arrivals must not receive automatic close requests")
assert(not find_session(starting), "late launch must not reopen a closed session")
assert(
	windows["address:0xa"].workspace.addressable_name == sessions.special_name("terminal"),
	"late terminal is adopted by active session"
)
complete_close("address:0xa")
assert(#sessions.state().sessions == 1 and sessions.state().active == "s1")
assert(not windows["address:0xc"], "session-local pins participate in normal closure")
-- Closed ownership must not reclaim a workspace promoted to global.
emit("config.unload")
config.global_specials = { radio = true, podcast = true, music = true }
events, timers, rules, cleanup_timers = {}, {}, {}, {}
sessions = dofile(module_path)
sessions.setup(config)
workspaces["special:music"].windows = 1
windows["address:0xd"] = { address = "0xd", workspace = workspaces["special:music"] }
workspaces[second_terminal].windows = 1
windows["address:0xe"] = { address = "0xe", workspace = workspaces[second_terminal] }
emit("window.open", windows["address:0xe"])
assert(not find_session("s2"), "late terminal must not restore its closed session")
assert(windows["address:0xe"].workspace.addressable_name == sessions.special_name("terminal"))
sessions.focus_window("address:0xd")
assert(sessions.state().active == "s1", "revived stale ownership must not capture global focus")
complete_close("address:0xe")
assert(windows["address:0xd"] and not find_session("s2"), "global player survives revived-session deletion")

-- Default is an ordinary session. It returns only after the final session closes.
local named = sessions.create("Only project")
local closed_default_workspace = windows["address:0x1"].workspace
sessions.close("s1")
assert(
	find_session("s1").closing and focused_window == "address:0x1",
	"show remaining app confirmation instead of an empty workspace"
)
sessions.switch(named)
sessions.switch("s1")
assert(focused_window == "address:0x1", "returning to a closing session must focus its remaining window")
complete_close("address:0x1")
assert(not find_session("s1") and sessions.state().active == named)
assert(
	#sessions.state().sessions == 1 and sessions.state().sessions[1].name == "Only project",
	"default must stay closed while named sessions remain"
)
emit("config.unload")
events, timers, rules, cleanup_timers = {}, {}, {}, {}
sessions = dofile(module_path)
sessions.setup(config)
emit("config.reloaded")
assert(#sessions.state().sessions == 1 and sessions.state().sessions[1].id == named, "reload must not recreate default")
closed_default_workspace.windows = 1
windows["address:0xf"] = { address = "0xf", workspace = closed_default_workspace }
emit("window.open", windows["address:0xf"])
assert(not find_session("s1") and #sessions.state().sessions == 1, "late default window must not resurrect default")
assert(
	windows["address:0xf"].workspace ~= closed_default_workspace,
	"late default window remains accessible in named session"
)
complete_close("address:0xf")
sessions.close(named)
drain_cleanup()
local fallback = sessions.state().active
assert(not find_session(named) and fallback ~= "s1" and #sessions.state().sessions == 1)
assert(
	find_session(fallback).name == "default" and find_session(fallback).window_count == 0,
	"closing last session creates a fresh empty default"
)
sessions.close(fallback)
drain_cleanup()
assert(sessions.state().active ~= fallback and #sessions.state().sessions == 1, "even the last default can be closed")
fallback = sessions.state().active
local prompts = sessions.create("Multiple confirmations")
local prompt_output = focused
local prompt_first = resolve(sessions.state().workspaces[prompt_output.name][1], prompt_output)
local prompt_second = resolve(sessions.state().workspaces[prompt_output.name][2], prompt_output)
prompt_first.windows, prompt_second.windows = 1, 1
windows["address:0x20"] = { address = "0x20", workspace = prompt_first }
windows["address:0x21"] = { address = "0x21", workspace = prompt_second }
sessions.close(prompts)
local first_focused = focused_window
local remaining = first_focused == "address:0x20" and "address:0x21" or "address:0x20"
complete_close(first_focused)
assert(focused_window == remaining, "when focused app exits, reveal remaining hidden close confirmation")
assert(
	prompt_output.active_workspace == windows[remaining].workspace,
	"remaining confirmation workspace must be visible"
)
complete_close(remaining)
assert(not find_session(prompts) and sessions.state().active == fallback)
local first_project = sessions.create("First project")
local first_workspace = focused.active_workspace
first_workspace.windows = 1
windows["address:0x10"] = { address = "0x10", workspace = first_workspace }
local second_project = sessions.create("Second project")
local second_workspace = focused.active_workspace
second_workspace.windows = 1
windows["address:0x11"] = { address = "0x11", workspace = second_workspace }
sessions.close(fallback)
sessions.close(first_project)
sessions.close(second_project)
assert(
	#sessions.state().sessions == 2 and find_session(first_project).closing and find_session(second_project).closing,
	"all named sessions may close concurrently"
)
complete_close("address:0x10")
assert(
	#sessions.state().sessions == 1 and find_session(second_project).closing,
	"do not create fallback while another closing session still exists"
)
complete_close("address:0x11")
assert(
	#sessions.state().sessions == 1 and sessions.state().sessions[1].name == "default",
	"create one fallback only after every named session exits"
)
assert(
	windows["address:0xd"] and windows["address:0x6"] and windows["address:0x7"],
	"fallback preserves global windows"
)
-- Existing/rule pins need no special keybinding to acquire session ownership.
local pin_session = sessions.state().active
local boot_pin = { address = "0xpinboot", workspace = focused.active_workspace, pinned = true, floating = true }
windows["address:0xpinboot"] = boot_pin
boot_pin.workspace.windows = boot_pin.workspace.windows + 1
emit("config.unload")
events, timers, rules = {}, {}, {}
sessions = dofile(module_path)
sessions.setup(config)
assert(find_session(pin_session).window_count == 1, "existing native pin is counted after reload")
local away = sessions.create("Away from pin")
assert(not boot_pin.pinned, "existing pin hides in another session")
sessions.close(pin_session)
assert(
	sessions.state().active == pin_session and boot_pin.pinned,
	"closing inactive pin session restores confirmation access"
)
assert(close_requests[#close_requests] == "address:0xpinboot", "close targets existing session-local pin")
complete_close("address:0xpinboot")
assert(
	not find_session(pin_session) and sessions.state().active == away,
	"pinned session retires only after window exits"
)
-- Remote-controlled terminals already received intentional close requests.
-- Their asynchronous exit must not reveal or re-close an inactive session.
local remote_session = sessions.create("Remote terminal close")
local remote_workspace = focused.active_workspace
remote_workspace.windows = 1
windows["address:0xremote"] = { address = "0xremote", workspace = remote_workspace }
sessions.switch(away)
local saved_focus, saved_workspace = focused_window, focused.active_workspace
local prior_requests = #close_requests
assert(find_session(remote_session).windows[1] == "0xremote", "publish exact owned window addresses")
sessions.close(remote_session, { ["0xremote"] = true })
drain_cleanup()
assert(sessions.state().active == away and focused_window == saved_focus, "remote close preserves background focus")
assert(focused.active_workspace == saved_workspace, "remote close never switches workspace")
assert(#close_requests == prior_requests, "remote-handled terminal never receives compositor close confirmation")
complete_close("address:0xremote")
assert(not find_session(remote_session) and sessions.state().active == away, "remote exit retires background session")
local active_remote = sessions.create("Active remote terminal close")
local active_workspace = focused.active_workspace
active_workspace.windows = 1
windows["address:0xactive"] = { address = "0xactive", workspace = active_workspace }
sessions.close(active_remote, { ["0xactive"] = true })
complete_close("address:0xactive")
assert(sessions.state().active == away, "active remote close returns to surviving session")
assert(#close_requests == prior_requests, "active remote close also skips compositor confirmation")
os.remove(base .. ".lua")
os.remove(base .. ".json")
print("sessions: scratchpads, session-local pins, reload, focus, hotplug, session closure, and default fallback passed")
