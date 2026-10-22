-- Run from any directory: lua /etc/nixos/home/features/desktop/hyprland/config/test_context_terminals.lua
local directory = assert(arg[0]:match("^(.*[/])"), "Use a path to this test")
package.path = directory .. "?.lua;" .. package.path
local count = 0
local function equal(actual, expected)
	assert(actual == expected, string.format("expected %s, got %s", tostring(expected), tostring(actual)))
end
local function fails(callback, message)
	local ok, err = pcall(callback)
	assert(not ok, "Expected failure")
	assert(tostring(err):find(message, 1, true), tostring(err))
end

local operations, launches, closes, views, switches
local engine, module, monitors, state
local fail_dispatch, fail_launch
local function reset()
	operations, launches, closes, views, switches = {}, {}, {}, {}, {}
	fail_dispatch, fail_launch = nil, false
	monitors = {}
	for _, name in ipairs({ "DP-1", "DP-2" }) do
		local monitor = {
			name = name, width = 3840, height = 2160, scale = 2, transform = 0,
			x = 0, y = 0, enabled = true, is_mirror = false,
		}
		function monitor:set_workspace(value)
			views[#views + 1] = { monitor = self.name, regular = value }
		end
		function monitor:set_special_workspace(value)
			views[#views + 1] = { monitor = self.name, special = value, clear = value == nil }
		end
		monitors[name] = monitor
	end
	state = {
		active = "s2",
		workspaces = { ["DP-1"] = { "adopted", "session-s2-44502d31-2" }, ["DP-2"] = { "4", "other" } },
		specials = { terminal = "special:session-s2-terminal", player = "special:player" },
	}
	engine = {
		close = function(id) closes[#closes + 1] = id; return "closed" end,
		state = function() return state end,
		switch = function(id) switches[#switches + 1] = id; state.active = id end,
	}
	engine.kill = engine.close
	package.loaded.sessions = engine
	package.loaded["context-terminals"] = nil
	local function operation(kind)
		return function(args) return { kind = kind, args = args } end
	end
	_G.hl = {
		get_monitor = function(name) return monitors[name] end,
		get_window = function(key) return key ~= "address:gone" and { address = key } or nil end,
		exec_cmd = function(command)
			if fail_launch then error("spawn failed") end
			launches[#launches + 1] = command
		end,
		dispatch = function(op)
			operations[#operations + 1] = op
			return { ok = op.kind ~= fail_dispatch, error = "dispatch refused" }
		end,
		dsp = {
			window = { float = operation("float"), move = operation("move"), resize = operation("resize"),
				fullscreen_state = operation("fullscreen") },
			workspace = { move = operation("workspace_move") },
		},
	}
	module = require("context-terminals")
end
local function test(name, callback)
	reset()
	callback()
	count = count + 1
	print("ok " .. count .. " - " .. name)
end
local function placement(overrides)
	local value = {
		address = "0x123", id = "logical-id", monitor = "DP-1", workspace = { slot = 2 },
		floating = true, geometry = { normalizedX = 0.25, normalizedY = 0.5, width = 0.5, height = 0.25 },
		fullscreen = 0, fullscreen_client = 0,
	}
	for key, item in pairs(overrides or {}) do value[key] = item end
	return value
end

test("close barrier, quoting, idempotence, legacy alias", function()
	fails(function() module.close_checkpointed("s2") end, "setup must run first")
	module.setup()
	local wrapped = engine.close
	module.setup()
	equal(engine.close, wrapped)
	engine.close("s'2; $(false)")
	equal(launches[1], "contextctl close --runtime 's'\\''2; $(false)'")
	equal(#closes, 0)
	engine.kill("s2")
	equal(#launches, 2)
	equal(#closes, 0) -- no coordinator callback, including checkpoint failure
	equal(module.close_checkpointed("s2"), "closed")
	equal(closes[1], "s2")
	equal(#launches, 2)
end)

test("spawn failure and invalid ID never raw-close", function()
	module.setup()
	fail_launch = true
	fails(function() engine.close("s2") end, "spawn failed")
	fails(function() engine.close("s\0x") end, "Invalid runtime ID")
	equal(#closes, 0)
end)

test("normalized floating placement and exact dispatch arguments", function()
	module.place("s2", placement())
	equal(#operations, 7)
	equal(operations[1].kind, "fullscreen")
	equal(operations[1].args.internal, 0)
	equal(operations[2].args.action, "enable")
	equal(operations[3].args.window, "address:0x123")
	equal(operations[3].args.workspace, "name:session-s2-44502d31-2")
	equal(operations[3].args.follow, false)
	equal(operations[4].kind, "workspace_move")
	equal(operations[4].args.monitor, "DP-1")
	equal(operations[5].args.x, 960)
	equal(operations[5].args.y, 270)
	equal(operations[6].args.x, 480)
	equal(operations[6].args.y, 540)
	equal(operations[6].args.relative, false)
	equal(#launches, 0)
end)

test("rotated scaled output, negative origin, clamp and legacy array", function()
	local monitor = monitors["DP-1"]
	monitor.transform, monitor.x, monitor.y = 1, -1080, -100
	module.place("s2", placement({ geometry = { 2, -0.5, 0.5, 4 } }))
	equal(operations[5].args.x, 540)
	equal(operations[5].args.y, 1920)
	equal(operations[6].args.x, -540)
	equal(operations[6].args.y, -100)
end)

test("minimum size and all odd transforms", function()
	for _, transform in ipairs({ 1, 3, 5, 7 }) do
		monitors["DP-1"].transform = transform
		operations = {}
		module.place("s2", placement({ geometry = { normalizedX = 1, Y = 1, width = 0, height = -2 } }))
		equal(operations[5].args.x, 1)
		equal(operations[5].args.y, 1)
		equal(operations[6].args.x, 1079)
		equal(operations[6].args.y, 1919)
	end
end)

test("missing/disabled/mirrored outputs rejected before mutation", function()
	for _, name in ipairs({ "missing", "DP-1", "DP-2" }) do
		monitors["DP-1"].enabled = false
		monitors["DP-2"].is_mirror = true
		fails(function() module.place("s2", placement({ monitor = name })) end, "Monitor unavailable")
	end
	equal(#operations, 0)
	equal(#switches, 0)
end)

test("stale window and bad geometry rejected before mutation", function()
	fails(function() module.place("s2", placement({ address = "gone" })) end, "no longer exists")
	fails(function() module.place("s2", placement({ geometry = { 0/0, 0, 1, 1 } })) end, "Invalid normalized")
	fails(function() module.place("s2", placement({ fullscreen = 4 })) end, "Invalid fullscreen")
	equal(#operations, 0)
end)

test("special placement and independent fullscreen client state", function()
	module.place("s2", placement({ workspace = { role = "terminal", slot = 1 }, fullscreen = 2, fullscreen_client = 1 }))
	equal(operations[3].args.workspace, "special:session-s2-terminal")
	equal(operations[7].args.internal, 2)
	equal(operations[7].args.client, 1)
	equal(operations[7].args.action, "set")
end)

test("tiled insertions replay sequentially; size approximate, never focus", function()
	module.place("s2", placement({ floating = false, address = "address:first" }))
	module.place("s2", placement({ floating = false, address = "second" }))
	equal(#operations, 18)
	equal(operations[7].kind, "float")
	equal(operations[7].args.action, "disable")
	equal(operations[7].args.window, "address:first")
	equal(operations[8].kind, "resize")
	equal(operations[16].args.window, "address:second")
	equal(operations[16].args.action, "disable")
end)

test("dispatch failure aborts placement", function()
	fail_dispatch = "workspace_move"
	fails(function() module.place("s2", placement()) end, "dispatch refused")
	equal(#operations, 4)
end)

test("view restores per-output slots, hides old specials, shows roles without launching", function()
	module.view("s2", { { monitor = "DP-1", slot = 1, role = "terminal" }, { monitor = "DP-2", slot = 1 } })
	equal(#views, 5)
	equal(views[1].clear, true)
	equal(views[2].regular, "name:adopted")
	equal(views[3].clear, true)
	equal(views[4].regular, "4")
	equal(views[5].special, "session-s2-terminal")
	equal(#launches, 0)
	equal(#operations, 0)
end)

test("background placement does not activate requested runtime", function()
	state.active = "s1"
	module.place("s2", placement())
	equal(state.active, "s1")
	equal(#switches, 0)
	equal(operations[3].args.workspace, "name:session-s2-44502d31-2")
end)

test("view leaves another active session untouched", function()
	state.active = "s1"
	equal(module.view("s2", { { monitor = "DP-2", slot = 2, role = "player" } }), false)
	equal(#switches, 0)
	equal(#views, 0)
	equal(#launches, 0)
end)

test("active view respects global special addresses", function()
	module.view("s2", { { monitor = "DP-2", slot = 2, role = "player" } })
	equal(#switches, 0)
	equal(views[2].regular, "name:other")
	equal(views[3].special, "player")
	equal(#launches, 0)
end)

test("invalid view fails without changing monitor view", function()
	fails(function() module.view("s2", { { monitor = "DP-1", slot = 1 }, { monitor = "absent", slot = 1 } }) end,
		"Monitor unavailable")
	fails(function() module.view("s2", { { monitor = "DP-1", slot = 1, role = "unknown" } }) end, "Unknown special")
	fails(function() module.view("s2", { { monitor = "DP-1", slot = 11 } }) end, "Slot must")
	equal(#views, 0)
end)

print(string.format("%d tests passed", count))
