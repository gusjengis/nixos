-- Live desktop sessions for the Lua-enabled Hyprland fork. No shell/UI dependency.
local M = {}
local state, options
local changing = false
local pending = {}
local launch_rules = {}
local finish_closing
local runtime = assert(os.getenv("XDG_RUNTIME_DIR"), "sessions requires XDG_RUNTIME_DIR")
local signature = assert(os.getenv("HYPRLAND_INSTANCE_SIGNATURE"), "sessions requires HYPRLAND_INSTANCE_SIGNATURE")
local base = runtime .. "/hyprland-sessions-" .. signature

local function encode(value, lua)
	local kind = type(value)
	if kind == "string" then
		if lua then
			return string.format("%q", value)
		end
		return '"' .. value:gsub('[%z\1-\31\\"]', function(c)
			return string.format("\\u%04x", c:byte())
		end) .. '"'
	elseif kind == "number" or kind == "boolean" then
		return tostring(value)
	elseif kind == "nil" then
		return lua and "nil" or "null"
	end
	local entries = {}
	local array = not lua and #value > 0
	for key, item in pairs(value) do
		local prefix = ""
		if not array then
			prefix = lua and ("[" .. encode(key, true) .. "]=") or (encode(key, false) .. ":")
		end
		entries[#entries + 1] = prefix .. encode(item, lua)
	end
	-- Arrays need deterministic order; pairs is not an ordering contract.
	if array then
		entries = {}
		for _, item in ipairs(value) do
			entries[#entries + 1] = encode(item, lua)
		end
	end
	return (lua or not array) and ("{" .. table.concat(entries, ",") .. "}")
		or ("[" .. table.concat(entries, ",") .. "]")
end

local function atomic_write(path, text)
	local file = assert(io.open(path .. ".tmp", "w"))
	assert(file:write(text))
	assert(file:close())
	assert(os.rename(path .. ".tmp", path))
end

local function session(id)
	for _, item in ipairs(state.sessions) do
		if item.id == id then
			return item
		end
	end
	error("Unknown desktop session: " .. tostring(id))
end

local function monitor(name)
	if name then
		return assert(hl.get_monitor(name), "Unknown monitor: " .. name)
	end
	return assert(hl.get_active_monitor(), "No active monitor")
end

local function outputs()
	local result = {}
	for _, output in ipairs(hl.get_monitors()) do
		if output.enabled ~= false and not output.is_mirror then
			result[#result + 1] = output
		end
	end
	return result
end

local function hex(value)
	return (value:gsub(".", function(c)
		return string.format("%02x", c:byte())
	end))
end

local function regular(item, output, slot)
	assert(type(slot) == "number" and slot % 1 == 0 and slot >= 1 and slot <= 10, "Workspace must be 1-10")
	item.workspaces[output] = item.workspaces[output] or {}
	local names = item.workspaces[output]
	names[slot] = names[slot] or ("session-" .. item.id .. "-" .. hex(output) .. "-" .. slot)
	return names[slot]
end

local function special(item, role)
	assert(options.specials[role], "Unknown special workspace: " .. tostring(role))
	if options.global_specials[role] then
		return assert(state.global_specials[role], "Global special workspace not initialized: " .. role)
	end
	item.specials[role] = item.specials[role] or ("special:session-" .. item.id .. "-" .. role)
	return item.specials[role]
end

local function address(workspace)
	return workspace and workspace.addressable_name
end

local function selector(name)
	return name:match("^special:") and name or (name:match("^%d+$") and name or "name:" .. name)
end

local function global_role(name)
	for role, candidate in pairs(state.global_specials) do
		if candidate == name then
			return role
		end
	end
end

local function owner(name)
	if global_role(name) then
		return
	end
	for _, item in ipairs(state.sessions) do
		for output, names in pairs(item.workspaces) do
			for slot, candidate in pairs(names) do
				if candidate == name then
					return item, output, slot
				end
			end
		end
		for role, candidate in pairs(item.specials) do
			if candidate == name then
				return item, nil, nil, role
			end
		end
	end
end

local function capture_pins()
	local present = {}
	for _, window in ipairs(hl.get_windows()) do
		local key = "address:" .. window.address
		present[key] = true
		local pin = state.pins[key]
		local name = address(window.workspace)
		if
			pin and (not owner(pin.workspace) or (not window.pinned and not pin.suspended) or window.floating == false)
		then
			state.pins[key] = nil
			pin = nil
		end
		if window.pinned and owner(name) then
			if not pin then
				state.pins[key] = { workspace = name }
			elseif owner(name) == owner(pin.workspace) then
				-- Native pins follow workspace changes within their session. Cross-session
				-- activation may already have migrated them before workspace.active fires.
				pin.workspace = name
			end
		end
	end
	for key in pairs(state.pins) do
		if not present[key] then
			state.pins[key] = nil
		end
	end
end

local function pin_window(key, action)
	local result = hl.dispatch(hl.dsp.window.pin({ window = key, action = action }))
	assert(result.ok, result.error)
end

local function park_pin(key, pin)
	local window = hl.get_window(key)
	if window and window.pinned and window.monitor and window.monitor.enabled ~= false then
		pin_window(key, "disable")
		pin.suspended = true
		-- Unpinning also assigns the monitor's active workspace. Put the window
		-- back if an external switch already carried it into another session.
		if address(window.workspace) ~= pin.workspace then
			hl.dispatch(hl.dsp.window.move({ window = key, workspace = selector(pin.workspace), follow = false }))
		end
	end
end

local function park_inactive_pins()
	capture_pins()
	local was_changing = changing
	changing = true
	local ok, err = pcall(function()
		for key, pin in pairs(state.pins) do
			if owner(pin.workspace).id ~= state.active then
				park_pin(key, pin)
			end
		end
	end)
	changing = was_changing
	assert(ok, err)
end

local function session_windows(item)
	local result = {}
	for _, window in ipairs(hl.get_windows()) do
		local name = address(window.workspace)
		local pin = state.pins["address:" .. window.address]
		if owner(pin and pin.workspace or name) == item then
			result[#result + 1] = window
		end
	end
	return result
end

local function focus_remaining(item)
	local window = session_windows(item)[1]
	if window then
		hl.dispatch(hl.dsp.focus({ window = "address:" .. window.address }))
	end
end

function M.state(id)
	capture_pins()
	-- Optional target exposes workspace addresses without activating that session.
	local active = session(id or state.active)
	local snapshot = { active = state.active, previous = state.previous, sessions = {}, workspaces = {}, specials = {} }
	for _, item in ipairs(state.sessions) do
		local windows = {}
		for _, window in ipairs(session_windows(item)) do
			windows[#windows + 1] = window.address
		end
		snapshot.sessions[#snapshot.sessions + 1] = {
			id = item.id,
			name = item.name,
			closing = item.closing or false,
			window_count = #windows,
			windows = windows,
			-- Logical remembered view is useful to any runtime-state consumer,
			-- including when this session is not currently visible.
			slots = item.slots,
			visible_specials = item.visible_specials,
		}
	end
	for _, output in ipairs(outputs()) do
		local names = {}
		for slot = 1, 10 do
			names[slot] = regular(active, output.name, slot)
		end
		snapshot.workspaces[output.name] = names
	end
	for role in pairs(options.specials) do
		snapshot.specials[role] = special(active, role)
	end
	return snapshot
end

local function publish()
	local snapshot = M.state()
	-- Lua data is private, same-user runtime state, loaded with an empty environment.
	-- Separate JSON snapshot is the public, read-only frontend protocol.
	atomic_write(base .. ".lua", "return " .. encode(state, true) .. "\n")
	atomic_write(base .. ".json", encode(snapshot, false) .. "\n")
end

local function remember()
	capture_pins()
	local item = session(state.active)
	for _, output in ipairs(outputs()) do
		local regular_owner, _, slot = owner(address(output.active_workspace))
		if regular_owner == item then
			item.slots[output.name] = slot
		end
		local name = address(output.active_special_workspace)
		local global = global_role(name)
		state.visible_globals[output.name] = global
		if not global then
			local special_owner, _, _, role = owner(name)
			item.visible_specials[output.name] = special_owner == item and role or nil
		end
	end
end

local function activate(item)
	local targets = outputs()
	assert(#targets > 0, "No active monitor; retry after a display reconnects")
	capture_pins()
	for key, pin in pairs(state.pins) do
		park_pin(key, pin)
	end
	local focused = hl.get_active_monitor()
	local globals = {}
	for _, output in ipairs(targets) do
		local name = address(output.active_special_workspace)
		local role = state.visible_globals[output.name]
		globals[output.name] = role and state.global_specials[role]
		if name ~= globals[output.name] then
			output:set_special_workspace(nil)
		end
	end
	for _, output in ipairs(targets) do
		output:set_workspace(selector(regular(item, output.name, item.slots[output.name] or 1)))
	end
	-- Native workspace activation can reattach pins orphaned by output teardown.
	-- Park those only after their window has regained a monitor reference.
	for key, pin in pairs(state.pins) do
		park_pin(key, pin)
	end
	for _, output in ipairs(targets) do
		local role = item.visible_specials[output.name]
		local global = globals[output.name]
		local name = global or (role and special(item, role))
		-- Local scratchpads must exist; globals may still await their first window.
		-- Switching never launches an application.
		if name and address(output.active_special_workspace) ~= name and (global or hl.get_workspace(name)) then
			output:set_special_workspace(name:sub(9))
		end
	end
	for key, pin in pairs(state.pins) do
		local window = hl.get_window(key)
		if
			owner(pin.workspace) == item
			and pin.suspended
			and window
			and window.monitor
			and window.monitor.enabled ~= false
		then
			pin_window(key, "enable")
			pin.suspended = nil
			pin.workspace = address(hl.get_window(key).workspace)
		end
	end
	if focused and focused.enabled ~= false and hl.get_monitor(focused.name) then
		hl.dispatch(hl.dsp.focus({ monitor = focused.name }))
	end
end

function M.switch(id)
	local target = session(id)
	if id == state.active then
		if target.closing then
			focus_remaining(target)
		end
		return
	end
	remember()
	local outgoing = state.active
	changing = true
	local ok, err = pcall(activate, target)
	local rollback_ok, rollback_err = true, nil
	if not ok then
		rollback_ok, rollback_err = pcall(activate, session(outgoing))
	end
	changing = false
	if not ok then
		publish()
		error(tostring(err) .. (rollback_ok and "" or ("; could not restore prior view: " .. tostring(rollback_err))))
	end
	state.previous, state.active = outgoing, id
	if target.closing then
		focus_remaining(target)
	end
	publish()
end

local function valid_name(name, except)
	assert(type(name) == "string", "Session name must be a string")
	name = name:match("^%s*(.-)%s*$")
	assert(name ~= "" and not name:find("[%z\1-\31\127]"), "Use a non-empty session name without control characters")
	for _, item in ipairs(state.sessions) do
		assert(item.id == except or item.name ~= name, "Session already exists: " .. name)
	end
	return name
end

local function add_session(name)
	local id = "s" .. state.next_id
	state.next_id = state.next_id + 1
	state.sessions[#state.sessions + 1] = {
		id = id,
		name = name,
		slots = {},
		visible_specials = {},
		workspaces = {},
		specials = {},
	}
	return state.sessions[#state.sessions]
end

function M.create(name)
	local item = add_session(valid_name(name))
	local ok, err = pcall(M.switch, item.id)
	if not ok then
		-- Do not reserve an invisible name after an unsuccessful activation.
		if state.active ~= item.id and #session_windows(item) == 0 then
			for index, candidate in ipairs(state.sessions) do
				if candidate == item then
					table.remove(state.sessions, index)
					break
				end
			end
		end
		publish()
		error(err)
	end
	return item.id
end

function M.rename(id, name)
	session(id).name = valid_name(name, id)
	publish()
end

function M.previous()
	if state.previous then
		M.switch(state.previous)
	end
end

function M.select_workspace(slot, output_name)
	local output = monitor(output_name)
	output:set_special_workspace(nil)
	output:set_workspace(selector(regular(session(state.active), output.name, slot)))
	hl.dispatch(hl.dsp.focus({ monitor = output.name }))
	remember()
	publish()
end

function M.move_window(slot, output_name)
	local output = monitor(output_name)
	hl.dispatch(hl.dsp.window.move({ workspace = selector(regular(session(state.active), output.name, slot)) }))
end

function M.cycle(offset)
	local output = monitor()
	local item = session(state.active)
	local _, _, slot = owner(address(output.active_workspace))
	M.select_workspace(((slot or item.slots[output.name] or 1) - 1 + offset) % 10 + 1, output.name)
end

function M.special_name(role)
	return special(session(state.active), role)
end

local function pending_request(name)
	if pending[name] then
		return pending[name], name
	end
	for source, request in pairs(pending) do
		if request.target == name then
			return request, source
		end
	end
end

local function arm_launch(name, request)
	local match = options.launch_matches and options.launch_matches[request.role]
	if match and not launch_rules[name] then
		-- Browsers may forward launches to an existing process, losing exec's PID
		-- association. A short-lived static rule places the next matching window.
		launch_rules[name] = hl.window_rule({
			name = "sessions-launch-" .. name:gsub(":", "-"),
			match = match,
			workspace = (request.target or name) .. " silent",
			no_initial_focus = true,
		})
	elseif launch_rules[name] then
		launch_rules[name]:set_enabled(true)
	end
	pending[name] = request
	hl.timer(function()
		if pending[name] == request then
			pending[name] = nil
			if launch_rules[name] then
				launch_rules[name]:set_enabled(false)
			end
			publish()
			finish_closing()
		end
	end, { timeout = math.max(1, (request.expires - os.time()) * 1000), type = "oneshot" })
end

function M.launch_special(role, command, expected_workspace)
	assert(
		options.global_specials[role] or not session(state.active).closing,
		"Session is closing; resolve any save dialogs first"
	)
	local name = M.special_name(role)
	assert(not expected_workspace or name == expected_workspace, "Active session changed")
	assert(type(command) == "string" and command ~= "", "Launch command must be non-empty")
	assert(not pending_request(name), "Application is still starting")
	if options.launch_matches and options.launch_matches[role] then
		for _, request in pairs(pending) do
			assert(request.role ~= role, "Application is still starting in another session")
		end
	end
	arm_launch(name, { role = role, expires = os.time() + 10 })
	hl.exec_cmd(command, { workspace = name .. " silent", no_initial_focus = true })
	publish()
end

function M.show_special(role, output_name)
	local output = monitor(output_name)
	local item = session(state.active)
	local name = special(item, role)
	-- This API adds special: itself; queries and exec rules use full addresses.
	output:set_special_workspace(name:sub(9))
	hl.dispatch(hl.dsp.focus({ monitor = output.name }))
	local workspace = hl.get_workspace(name)
	if workspace and workspace.windows == 0 and not pending_request(name) then
		local command = options.specials[role]
		if type(command) == "function" then
			command = command(item.id, signature)
		end
		if command then
			M.launch_special(role, command)
		end
	end
	for source, request in pairs(pending) do
		if source == name or request.target == name then
			request.reveal = true
		end
	end
	remember()
	publish()
end

function M.toggle_special(role, output_name)
	local output = monitor(output_name)
	if address(output.active_special_workspace) == M.special_name(role) then
		output:set_special_workspace(nil)
		remember()
		publish()
	else
		M.show_special(role, output.name)
	end
end

function M.focus_window(window_address)
	local window = assert(hl.get_window(window_address), "Window no longer exists")
	local pin = state.pins["address:" .. window.address]
	local item = owner(pin and pin.workspace or address(window.workspace))
	if item then
		M.switch(item.id)
	end
	hl.dispatch(hl.dsp.focus({ window = window_address }))
end

finish_closing = function()
	for index = #state.sessions, 1, -1 do
		local item = state.sessions[index]
		local launching = false
		for source, request in pairs(pending) do
			if owner(request.target or source) == item then
				launching = true
				break
			end
		end
		if item.closing and not launching and #session_windows(item) == 0 then
			local replacement
			for _, candidate in ipairs(state.sessions) do
				if candidate ~= item and not candidate.closing then
					replacement = candidate
					if candidate.id == state.previous then
						break
					end
				end
			end
			if not replacement then
				for _, candidate in ipairs(state.sessions) do
					if candidate ~= item then
						replacement = candidate
						break
					end
				end
			end
			-- Only create a fallback once the final session actually finishes closing.
			replacement = replacement or add_session("default")
			if state.active == item.id then
				changing = true
				local ok, err = pcall(activate, replacement)
				changing = false
				assert(ok, err)
				state.active, state.previous = replacement.id, nil
				if replacement.closing then
					focus_remaining(replacement)
				end
			end
			-- Keep addresses recoverable if an already-started app maps late.
			item.closing = nil
			state.retired_sessions[item.id] = item
			table.remove(state.sessions, index)
			if state.previous == item.id then
				state.previous = nil
			end
			publish()
		end
	end
end

local cleanup_scheduled = false
local function schedule_cleanup()
	if cleanup_scheduled then
		return
	end
	cleanup_scheduled = true
	hl.timer(function()
		cleanup_scheduled = false
		finish_closing()
		local active = session(state.active)
		if active.closing and not hl.get_active_window() then
			focus_remaining(active)
		end
		publish()
	end, { timeout = 25, type = "oneshot" })
end

function M.close(id, handled)
	local item = session(id)
	local windows = session_windows(item)
	handled = handled or {}
	local needs_attention = false
	for _, window in ipairs(windows) do
		if not handled[window.address] then
			needs_attention = true
		end
	end
	if needs_attention then
		-- Bring save dialogs into view, then return to the prior session on exit.
		M.switch(id)
	end
	item.closing = true
	publish()
	for _, window in ipairs(windows) do
		if not handled[window.address] then
			hl.dispatch(hl.dsp.window.close({ window = "address:" .. window.address }))
		end
	end
	-- A confirmation can be inside an existing terminal on a hidden workspace.
	if needs_attention then
		focus_remaining(item)
	end
	finish_closing()
	schedule_cleanup()
end

-- Keep the previously published command usable by existing clients.
M.kill = M.close

function M.setup(config)
	assert(not state, "sessions.setup must only run once per config load")
	options = config or {}
	options.specials = options.specials or {}
	options.global_specials = options.global_specials or {}
	local restore = loadfile(base .. ".lua", "t", {})
	if restore then
		state = restore()
	else
		state = {
			active = "s1",
			next_id = 2,
			sessions = {
				{ id = "s1", name = "default", slots = {}, visible_specials = {}, workspaces = {}, specials = {} },
			},
		}
		local initial = session(state.active)
		-- Adopt existing addresses, not windows. This fork's rename only changes a
		-- display label, and special workspaces cannot be renamed at all.
		for _, workspace in ipairs(hl.get_workspaces()) do
			local name = address(workspace)
			local role = name:match("^special:(.+)$")
			if role and options.specials[role] then
				initial.specials[role] = name
			elseif not workspace.special and workspace.monitor then
				local slot = tonumber(name:match(":(%d+)$")) or workspace.id
				if slot and slot >= 1 and slot <= 10 then
					regular(initial, workspace.monitor.name, slot)
					initial.workspaces[workspace.monitor.name][slot] = name
				end
			end
		end
	end
	state.global_specials = state.global_specials or {}
	state.visible_globals = state.visible_globals or {}
	state.retired_sessions = state.retired_sessions or {}
	state.pins = state.pins or {}
	-- Scope changes survive reloads. Reuse the existing player workspace; if
	-- several sessions already have copies, consolidate without closing windows.
	for role, name in pairs(state.global_specials) do
		if not options.global_specials[role] then
			session(state.active).specials[role] = name
			for _, output in ipairs(outputs()) do
				if address(output.active_special_workspace) == name then
					session(state.active).visible_specials[output.name] = role
				end
			end
			state.global_specials[role] = nil
		end
	end
	for role, enabled in pairs(options.global_specials) do
		if enabled then
			assert(options.specials[role], "Unknown global special workspace: " .. role)
			local candidates = { "special:" .. role }
			for _, item in ipairs(state.sessions) do
				if item.specials[role] then
					candidates[#candidates + 1] = item.specials[role]
				end
			end
			local name = state.global_specials[role]
			if not name then
				for _, candidate in ipairs(candidates) do
					local workspace = hl.get_workspace(candidate)
					if workspace and workspace.windows > 0 then
						name = candidate
						break
					end
				end
			end
			if not name then
				for _, candidate in ipairs(candidates) do
					local request = state.pending and state.pending[candidate]
					if request and request.expires > os.time() then
						name = candidate
						break
					end
				end
			end
			name = name or candidates[1]
			state.global_specials[role] = name
			for _, candidate in ipairs(candidates) do
				local workspace = hl.get_workspace(candidate)
				local output = workspace and workspace.monitor
				local visible = output and address(output.active_special_workspace) == candidate
				if candidate ~= name and workspace and workspace.windows > 0 then
					for _, window in ipairs(hl.get_windows({ workspace = workspace })) do
						hl.dispatch(hl.dsp.window.move({
							window = "address:" .. window.address,
							workspace = name,
							follow = false,
						}))
					end
				end
				local request = state.pending and state.pending[candidate]
				if candidate ~= name and request then
					request.target = name
				end
				if candidate ~= name and visible then
					output:set_special_workspace(name:sub(9))
				end
			end
			for _, item in ipairs(state.sessions) do
				item.specials[role] = nil
				for output, visible in pairs(item.visible_specials) do
					if visible == role then
						item.visible_specials[output] = nil
					end
				end
			end
		end
	end
	for output, role in pairs(state.visible_globals) do
		if not options.global_specials[role] then
			state.visible_globals[output] = nil
		end
	end
	for _, output in ipairs(outputs()) do
		local role = global_role(address(output.active_special_workspace))
		if role then
			state.visible_globals[output.name] = role
		end
	end
	pending = state.pending or {}
	state.pending = pending
	for name, request in pairs(pending) do
		if request.expires > os.time() and options.specials[request.role] then
			arm_launch(name, request)
		else
			pending[name] = nil
		end
	end
	if not restore then
		remember()
	end

	local function workspace_changed(workspace)
		if changing or not workspace then
			return
		end
		-- Disconnect migration can activate replacement workspaces before the
		-- monitor.removed event. Those transitions are not user session switches.
		if workspace.monitor and workspace.monitor.enabled == false then
			return
		end
		local item, _, slot, role = owner(address(workspace))
		if item and item.id ~= state.active then
			local output = workspace.monitor
			if output and slot then
				item.slots[output.name] = slot
			elseif output and role then
				item.visible_specials[output.name] = role
			end
			M.switch(item.id)
		else
			remember()
			publish()
		end
	end
	hl.on("workspace.active", workspace_changed)
	hl.on("workspace.special_active", function(workspace)
		if workspace then
			workspace_changed(workspace)
		elseif not changing then
			remember()
			publish()
		end
	end)
	hl.on("window.open", function(window)
		local name = address(window.workspace)
		if name then
			local request, source = pending_request(name)
			if request then
				pending[source] = nil
				if request.target and request.target ~= name then
					name = request.target
					hl.dispatch(
						hl.dsp.window.move({ window = "address:" .. window.address, workspace = name, follow = false })
					)
				end
			end
			if launch_rules[source or name] then
				launch_rules[source or name]:set_enabled(false)
			end
			local focused = hl.get_active_monitor()
			local item = owner(name)
			if not item and not global_role(name) then
				for _, retired in pairs(state.retired_sessions) do
					local matches = false
					for _, names in pairs(retired.workspaces) do
						for _, candidate in pairs(names) do
							matches = matches or candidate == name
						end
					end
					local role_match
					for role, candidate in pairs(retired.specials) do
						if candidate == name then
							matches, role_match = true, role
							break
						end
					end
					if matches then
						-- Preserve late windows without reopening an explicitly closed session.
						local target = session(state.active)
						local output = window.monitor or hl.get_active_monitor()
						local was_active = window.active
						if role_match and options.specials[role_match] then
							name = special(target, role_match)
						else
							name = regular(target, output.name, target.slots[output.name] or 1)
						end
						hl.dispatch(hl.dsp.window.move({
							window = "address:" .. window.address,
							workspace = selector(name),
							follow = false,
						}))
						item = owner(name)
						if was_active then
							hl.dispatch(hl.dsp.focus({ window = "address:" .. window.address }))
						end
						publish()
						break
					end
				end
			end
			if
				request
				and request.reveal
				and not (item and item.closing)
				and ((item and item.id == state.active) or global_role(name))
				and focused
				and address(focused.active_special_workspace) == name
			then
				hl.dispatch(hl.dsp.focus({ window = "address:" .. window.address }))
			end
			if request or (item and item.closing) then
				publish()
			end
		end
		park_inactive_pins()
	end)
	hl.on("window.pin", function(window)
		if changing then
			return
		end
		local key = "address:" .. window.address
		local name = address(window.workspace)
		state.pins[key] = window.pinned and owner(name) and { workspace = name } or nil
		park_inactive_pins()
		publish()
	end)
	hl.on("window.close", schedule_cleanup)
	hl.on("window.move_to_workspace", schedule_cleanup)
	hl.on("config.unload", function()
		remember()
		publish()
	end)
	local function reconcile()
		-- Monitor disconnects may move hidden workspaces to a surviving output.
		-- Re-establish the active session after compositor finishes output changes.
		hl.timer(function()
			if #outputs() == 0 then
				publish()
				return
			end
			changing = true
			local ok, err = pcall(activate, session(state.active))
			changing = false
			assert(ok, err)
			publish()
			finish_closing()
		end, { timeout = 100, type = "oneshot" })
	end
	hl.on("monitor.added", reconcile)
	hl.on("monitor.removed", reconcile)
	hl.on("config.reloaded", reconcile)
	park_inactive_pins()
	publish()
end

return M
