local M = {}

local hugeMarginsByMonitor = {}
local fullscreenByMonitor = {}
local rulesByMonitor = {}
local barRulesByMonitor = {}
-- Quickshell starts with the bar shown; use the same state before its IPC sync
-- so initial huge-margin rules reserve the bar offset immediately.
local barVisible = true
local statePath = (os.getenv("XDG_RUNTIME_DIR") or "/tmp") .. "/hyprland-monitor-modes.json"

local function writeState()
	local names = {}
	for name in pairs(hugeMarginsByMonitor) do
		table.insert(names, name)
	end
	table.sort(names)

	local entries = {}
	for _, name in ipairs(names) do
		local escaped = name:gsub("\\", "\\\\"):gsub('"', '\\"')
		table.insert(entries, string.format('"%s":%s', escaped, hugeMarginsByMonitor[name] and "true" or "false"))
	end

	local temporaryPath = statePath .. ".tmp"
	local file = assert(io.open(temporaryPath, "w"))
	file:write('{"hugeMargins":{', table.concat(entries, ","), "}}\n")
	file:close()
	assert(os.rename(temporaryPath, statePath))
end

local function setRulesEnabled(name, enabled)
	for _, rule in ipairs(rulesByMonitor[name]) do
		rule:set_enabled(enabled)
	end
	if barRulesByMonitor[name] then
		for _, rule in ipairs(barRulesByMonitor[name]) do
			rule:set_enabled(enabled and barVisible)
		end
	end
end

function M.set_bar_visible(visible)
	barVisible = visible
	for name, rules in pairs(barRulesByMonitor) do
		for _, rule in ipairs(rules) do
			rule:set_enabled(hugeMarginsByMonitor[name] and not fullscreenByMonitor[name] and barVisible)
		end
	end
end

function M.set_fullscreen(name, fullscreen)
	if hugeMarginsByMonitor[name] == nil then
		return
	end

	fullscreenByMonitor[name] = fullscreen
	setRulesEnabled(name, hugeMarginsByMonitor[name] and not fullscreen)
end

function M.toggle()
	local monitor = hl.get_active_monitor()
	if not monitor or hugeMarginsByMonitor[monitor.name] == nil then
		return
	end

	hugeMarginsByMonitor[monitor.name] = not hugeMarginsByMonitor[monitor.name]
	setRulesEnabled(monitor.name, hugeMarginsByMonitor[monitor.name] and not fullscreenByMonitor[monitor.name])
	writeState()
end

function M.configure(monitors)
	for name, mode in pairs(monitors) do
		hugeMarginsByMonitor[name] = mode.enabled
		fullscreenByMonitor[name] = false
		rulesByMonitor[name] = {}
		table.insert(
			rulesByMonitor[name],
			hl.workspace_rule({
				workspace = "m[" .. name .. "]",
				gaps_out = mode.multiple_window_margins or mode.margins,
				enabled = mode.enabled,
			})
		)

		if mode.bar_margins then
			barRulesByMonitor[name] = {}
			for _, special in ipairs({ false, true }) do
				table.insert(
					barRulesByMonitor[name],
					hl.workspace_rule({
						workspace = "m[" .. name .. "] s[" .. tostring(special) .. "]",
						gaps_out = mode.bar_margins,
						enabled = mode.enabled and barVisible,
					})
				)
			end
		end

		if mode.single_window_margins then
			table.insert(
				rulesByMonitor[name],
				hl.workspace_rule({
					workspace = "m[" .. name .. "] w[1]",
					gaps_out = mode.single_window_margins,
					enabled = mode.enabled,
				})
			)
		end
	end

	writeState()

	hl.bind("SUPER + F12", M.toggle, {
		description = "Toggle Huge Margins on Active Monitor",
	})
end

return M
