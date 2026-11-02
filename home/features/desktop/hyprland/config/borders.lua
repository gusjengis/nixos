local dataHome = os.getenv("XDG_DATA_HOME") or (os.getenv("HOME") .. "/.local/share")
local library = dataHome .. "/hypr-borders/borders-plus-plus.so"
local file = io.open(library, "rb")
if not file then
	return
end
file:close()

hl.plugin.load(library)
hl.config({
	plugin = {
		borders_plus_plus = {
			add_borders = 1,
			natural_rounding = false,
			border_size_1 = 1,
			col = { border_1 = "rgba(000000ff)" },
		},
	},
})
