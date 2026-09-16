hl.on("hyprland.start", function()
	hl.exec_cmd("xset r rate 190 50")
	hl.exec_cmd("hyprctl setcursor $cursor_theme $cursor_size")
	hl.exec_cmd("systemctl --user start --no-block thunar.service")
	hl.exec_cmd("hyprsunset")
	hl.exec_cmd("hypridle")
	hl.exec_cmd("awww-daemon --quiet")

	-- NOT REPRODUCIBLE: hyprlogd and timeline-hyprfocusd-snitch are installed by
	-- hand with `cargo install` into ~/.cargo/bin, so they only run where that
	-- has been done. Deliberate for now; hyprlog is being rewritten and will be
	-- packaged in packages/ when it is.
	hl.exec_cmd("hyprlogd snitch")
	hl.exec_cmd("timeline-hyprfocusd-snitch")

	-- hl.exec_cmd("alga power on")

	-- Low-battery warnings are a systemd user timer now, on laptops only.
	-- See features/hardware/battery.

	hl.exec_cmd("kdeconnect-indicator")
	hl.exec_cmd("qs -d -n")
	hl.exec_cmd("handy --start-hidden")
	hl.exec_cmd("mailspring --background")
end)
