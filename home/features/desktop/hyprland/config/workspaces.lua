local vars = require("platform-variables")

local workspaces = {
	{ name = "terminal", key = "T", description = "Terminal", command = vars.terminal .. " --hold ta" },
	{ name = "browser", key = "C", description = "Chromium", command = vars.browser },
	{ name = "calendar", key = "C", description = "Calendar", command = vars.calendar, shift = true },
	{ name = "gpt", key = "G", description = "ChatGPT", command = vars.gpt },
	{ name = "gis", key = "G", description = "GIS", command = vars.gis, shift = true },
	{ name = "db", key = "D", description = "DB", command = vars.db, shift = true },
	{ name = "slack", key = "S", description = "Slack", command = vars.slack },
	{ name = "discord", key = "D", description = "Discord", command = vars.discord },
	{ name = "notes", key = "N", description = "Notes", command = "obsidian" },
	{ name = "music", key = "Q", description = "Music", command = vars.music, shift = true },
	{ name = "musicassistant", key = "M", description = "Music Assistant", command = vars.music_assistant },
	{ name = "email", key = "E", description = "Email", command = vars.email },
	{ name = "home", key = "H", description = "Home Assistant", command = vars.homeAssistant, shift = true },
}

for _, workspace in ipairs(workspaces) do
	local modifiers = vars.SUPER .. (workspace.shift and " + SHIFT" or "")

	hl.bind(modifiers .. " + " .. workspace.key, hl.dsp.workspace.toggle_special(workspace.name), {
		description = workspace.description,
	})
	hl.workspace_rule({
		workspace = "special:" .. workspace.name,
		on_created_empty = workspace.command,
	})
end

hl.window_rule({
	name = "disable-auto-hdr-kitty",
	match = { class = "kitty" },
	no_auto_hdr = true,
})
