-- Personal checkpoint policy. Wire setup() AFTER sessions.setup() in main.
-- The coordinator owns durable checkpoints, monitor fallback, saved-order replay,
-- and final focus. This module never checkpoints or launches restored apps itself.
local M = {}
local sessions, original_close

local function shell_quote(value)
	assert(type(value) == "string" and value ~= "" and not value:find("%z"), "Invalid runtime ID")
	return "'" .. value:gsub("'", "'\\''") .. "'"
end

function M.setup()
	if original_close then
		return
	end
	sessions = require("sessions")
	original_close = assert(sessions.close, "sessions.close is unavailable")
	local function checkpoint_then_close(id)
		-- hl.exec_cmd spawns asynchronously and returns no exit status. Only the
		-- coordinator may call close_checkpointed after a synchronous checkpoint.
		-- Failed launch/checkpoint has NO fallback to original_close.
		hl.exec_cmd("contextctl close --runtime " .. shell_quote(id))
	end
	sessions.close = checkpoint_then_close
	if sessions.kill == original_close then
		sessions.kill = checkpoint_then_close
	end
end

function M.close_checkpointed(id, handled)
	assert(original_close, "context-terminals.setup must run first")
	return original_close(id, handled)
end

local function dispatch(operation)
	local result = hl.dispatch(operation)
	assert(result and result.ok, result and result.error or "Dispatch failed")
end

local function output(name)
	assert(type(name) == "string" and name ~= "", "Coordinator must supply a monitor name")
	local monitor = assert(hl.get_monitor(name), "Monitor unavailable: " .. name)
	assert(monitor.enabled ~= false and not monitor.is_mirror, "Monitor unavailable: " .. name)
	return monitor
end

local function snapshot(id)
	return require("sessions").state(id)
end

local function workspace(state, monitor, slot, role)
	if role ~= nil then
		assert(type(role) == "string" and state.specials[role], "Unknown special role: " .. tostring(role))
		return state.specials[role]
	end
	assert(type(slot) == "number" and slot % 1 == 0 and slot >= 1 and slot <= 10, "Slot must be 1-10")
	return assert(state.workspaces[monitor] and state.workspaces[monitor][slot], "Missing runtime workspace")
end

local function selector(name)
	return name:match("^special:") and name or (name:match("^%d+$") and name or "name:" .. name)
end

local function finite(value)
	return type(value) == "number" and value == value and math.abs(value) < math.huge
end

local function clamp(value, lower, upper)
	return math.max(lower, math.min(value, upper))
end

local function round(value)
	return math.floor(value + 0.5)
end

local function rectangle(monitor, geometry)
	assert(type(geometry) == "table", "Missing normalized geometry")
	-- Object contract; numeric array also accepts existing coordinator snapshots.
	local nx = geometry.normalizedX or geometry[1]
	local ny = geometry.normalizedY or geometry.Y or geometry[2]
	local nw = geometry.width or geometry[3]
	local nh = geometry.height or geometry[4]
	assert(finite(nx) and finite(ny) and finite(nw) and finite(nh), "Invalid normalized geometry")
	assert(finite(monitor.scale) and monitor.scale > 0, "Invalid monitor scale")
	-- LuaMonitor.width/height expose untransformed m_pixelSize. Monitor.cpp
	-- computes logical m_size by swapping odd transforms, dividing, then rounding.
	local pw, ph = monitor.width, monitor.height
	if monitor.transform % 2 == 1 then
		pw, ph = ph, pw
	end
	local w, h = round(pw / monitor.scale), round(ph / monitor.scale)
	assert(w >= 1 and h >= 1, "Invalid logical monitor size")
	local width, height = clamp(round(nw * w), 1, w), clamp(round(nh * h), 1, h)
	return {
		x = monitor.x + clamp(round(nx * w), 0, w - width),
		y = monitor.y + clamp(round(ny * h), 0, h - height),
		width = width,
		height = height,
	}
end

local function fullscreen_mode(value)
	value = value or 0
	assert(type(value) == "number" and value % 1 == 0 and value >= 0 and value <= 3, "Invalid fullscreen mode")
	return value
end

function M.place(runtime_id, placement)
	local monitor = output(placement.monitor) -- Missing-output policy belongs to coordinator.
	assert(type(placement.address) == "string" and placement.address ~= "", "Missing mapped window address")
	local key = placement.address:match("^address:") and placement.address or "address:" .. placement.address
	assert(hl.get_window(key), "Mapped window no longer exists")
	assert(type(placement.floating) == "boolean", "Missing floating state")
	local box = rectangle(monitor, placement.geometry)
	local internal, client = fullscreen_mode(placement.fullscreen), fullscreen_mode(placement.fullscreen_client)
	local state = snapshot(runtime_id)
	local logical = assert(placement.workspace, "Missing logical workspace")
	local name = workspace(state, monitor.name, logical.slot, logical.role)
	local target = selector(name)
	-- Exact fork APIs: LuaBindingsDispatchers.cpp fullscreen_state (738), float
	-- (677), move workspace/position (780), resize (1028), workspace.move (1268).
	dispatch(hl.dsp.window.fullscreen_state({ window = key, internal = 0, client = 0, action = "set" }))
	-- Remove initial tiling insertion even if the fresh window mapped at target.
	dispatch(hl.dsp.window.float({ window = key, action = "enable" }))
	dispatch(hl.dsp.window.move({ window = key, workspace = target, follow = false }))
	-- New workspaces are otherwise created on the focused output, not necessarily
	-- the requested one. Moving the workspace also handles special workspaces.
	dispatch(hl.dsp.workspace.move({ workspace = target, monitor = monitor.name }))
	dispatch(hl.dsp.window.resize({ window = key, x = box.width, y = box.height, relative = false }))
	dispatch(hl.dsp.window.move({ window = key, x = box.x, y = box.y, relative = false }))
	if not placement.floating then
		-- Replay coordinator order without timers/batching. Native dwindle chooses
		-- insertion from focus/cursor/config; resize only approximates saved splits.
		dispatch(hl.dsp.window.float({ window = key, action = "disable" }))
		dispatch(hl.dsp.window.resize({ window = key, x = box.width, y = box.height, relative = false }))
	end
	dispatch(hl.dsp.window.fullscreen_state({ window = key, internal = internal, client = client, action = "set" }))
	return true
end

function M.view(runtime_id, view)
	-- Background restoration must not reclaim focus after the user switches away.
	if require("sessions").state().active ~= runtime_id then
		return false
	end
	-- Validate all output references before switching. No implicit monitor fallback.
	local targets, seen = {}, {}
	for _, item in ipairs(view) do
		local monitor = output(item.monitor)
		assert(not seen[monitor.name], "Duplicate view monitor: " .. monitor.name)
		seen[monitor.name] = true
		targets[#targets + 1] = { monitor = monitor, slot = item.slot, role = item.role }
	end
	local state = snapshot(runtime_id)
	for _, item in ipairs(targets) do
		item.regular = workspace(state, item.monitor.name, item.slot)
		item.special = item.role and workspace(state, item.monitor.name, item.slot, item.role)
	end
	-- Restore regular slots first, then visible scratchpads. Unlike show_special,
	-- these source-verified monitor methods never run configured launch commands.
	for _, item in ipairs(targets) do
		item.monitor:set_special_workspace(nil)
		item.monitor:set_workspace(selector(item.regular))
	end
	for _, item in ipairs(targets) do
		if item.special then
			item.monitor:set_special_workspace(item.special:sub(9))
		end
	end
	return true
end

-- No invented tree APIs: LuaWorkspace.cpp:148-175 exposes only layout name,
-- windows/groups, not native nodes. LuaLayoutProvider.cpp:321-328 registers
-- custom providers only. DwindleAlgorithm.cpp:676-769 accepts togglesplit,
-- swapsplit, rotatesplit, movetoroot, preselect, splitratio; no tree serialization.
return M
