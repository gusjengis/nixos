local vars = require("platform-variables")
local features = require("desktop-features")
if not features.contexts then
	-- Plain Hyprland workspaces need no saved-context manager.
	return
end
local sessions = require("sessions")

local workspaces = {
	{
		name = "terminal",
		key = "T",
		description = "Terminal",
		command = function(id, signature)
			return "contextctl terminal --runtime " .. id
		end,
	},
	{ name = "browser", key = "C", description = "Chromium", command = vars.browser .. " --new-window" },
	{ name = "calendar", key = "C", description = "Calendar", command = vars.calendar, shift = true },
	{ name = "gpt", key = "G", description = "ChatGPT", command = vars.gpt },
	{ name = "gis", key = "G", description = "GIS", command = vars.gis, shift = true },
	{ name = "db", key = "D", description = "DB", command = vars.db, shift = true },
	-- { name = "slack", key = "S", description = "Slack", command = vars.slack },
	{ name = "discord", key = "D", description = "Discord", command = vars.discord },
	{
		name = "notes",
		key = "N",
		description = "Context Notes",
		command = function(id)
			return "contextctl notes --runtime " .. id
		end,
	},
	{ name = "music", key = "Q", description = "Music", command = vars.music, shift = true, global = true },
	{
		name = "musicassistant",
		key = "M",
		description = "Music Assistant",
		command = vars.music_assistant,
		global = true,
	},
	{ name = "email", key = "E", description = "Email", command = vars.email },
	{ name = "home", key = "H", description = "Home Assistant", command = vars.homeAssistant, shift = true },
}

local specials = {}
local global_specials = {}
for _, workspace in ipairs(workspaces) do
	specials[workspace.name] = workspace.command
	global_specials[workspace.name] = workspace.global
end
sessions.setup({
	specials = specials,
	global_specials = global_specials,
	launch_matches = {
		browser = { class = "^(chromium|chromium-browser|Chromium)$" },
	},
})
require("context-terminals").setup()

for _, workspace in ipairs(workspaces) do
	local modifiers = vars.SUPER .. (workspace.shift and " + SHIFT" or "")

	hl.bind(modifiers .. " + " .. workspace.key, function()
		sessions.toggle_special(workspace.name)
	end, {
		description = workspace.description,
	})
end

hl.window_rule({
	name = "disable-auto-hdr-kitty",
	match = { class = "kitty" },
	no_auto_hdr = true,
})
