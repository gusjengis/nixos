import Quickshell
import Quickshell.Hyprland
import "../../state"

PopupWindow {
    id: popup

    grabFocus: false

    HyprlandFocusGrab {
        active: popup.visible && !FocusGuard.suspended
        windows: [popup]
        onCleared: {
            if (!FocusGuard.suspended)
                popup.visible = false;
        }
    }
}
