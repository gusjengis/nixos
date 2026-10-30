import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    InProgressWidget {}

    IpcHandler {
        target: "sessions"
        function toggle(): void { contextOrganizer.visible = false; sessionPicker.toggle(false); }
        function dispensary(): void { sessionPicker.visible = false; contextOrganizer.toggle(); }
    }

    SessionPicker { id: sessionPicker }
    ContextOrganizer { id: contextOrganizer }
}
