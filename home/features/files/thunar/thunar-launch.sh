set -euo pipefail

config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
private_home="${XDG_STATE_HOME:-$HOME/.local/state}/thunar-gtk"
mkdir -p "$private_home/gtk-3.0"

# Keep bookmarks and xfconf shared with the real user config. Only GTK theme,
# icon theme, font and colors live in the private directory.
ln -sfn "$config_home/gtk-3.0/bookmarks" "$private_home/gtk-3.0/bookmarks"
ln -sfn "$config_home/xfce4" "$private_home/xfce4"
ln -sfn "@CSS@" "$private_home/gtk-3.0/gtk.css"

export XDG_CONFIG_HOME="$private_home"
export GTK_THEME=adw-gtk3-dark
exec "@THUNAR@/bin/Thunar" "$@"
