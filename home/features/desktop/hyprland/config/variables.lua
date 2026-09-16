-- trying to hide window decorations, doesn't seem to work
hl.env("QT_WAYLAND_DISABLE_WINDOWDECORATION", "1")
hl.env("GTK_CSD", "0")

local home = os.getenv("HOME")
local repo = os.getenv("NIXOS_CONFIG_ROOT") or "/etc/nixos"
local desktopLauncher = repo .. "/home/features/desktop/webapps/launch-desktop-entry.sh"

return {
	SUPER = "SUPER",
	terminal = "kitty",
	browser = "chromium",
	desktopLauncher = desktopLauncher,
	email = "mailspring",
	music = desktopLauncher .. " webapp-qobuz",
	onedrive = desktopLauncher .. " webapp-onedrive",
	unity = home .. "/Unity/Hub/Editor/6000.0.23f1/Editor/Unity '" .. home .. "/Cloud Repositories/3DT/'",
	gpt = desktopLauncher .. " webapp-chatgpt",
	gis = "chromium --app=https://mattgeocore.co.pierce.wa.us/login/home?filter=cvwebext",
	db = "chromium --app=https://database.azuregreenconsultants.com/map",
	claude = desktopLauncher .. " webapp-claude",
	fileManager = "thunar",
	whatsapp = desktopLauncher .. " webapp-whatsapp",
	excel = desktopLauncher .. " webapp-excel",
	calendar = desktopLauncher .. " webapp-calendar",
	todos = desktopLauncher .. " webapp-todoist",
	homeAssistant = desktopLauncher .. " webapp-home-assistant",
	music_assistant = desktopLauncher .. " webapp-music-assistant",
}
