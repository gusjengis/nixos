//@ pragma UseQApplication

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import "bar"
import "state"
import "theme"

// QuickShell launcher shell. Two dedicated popups: a local application launcher
// and a remote launcher (Tailnet host picker, then applications on a chosen
// host). The UI lives in Launcher.qml (and its RequestProcess.qml /
// LaunchProcess.qml helpers).
ShellRoot {
    id: root

    Bar { }

    IpcHandler {
        target: "focusGuard"
        function suspend(): void { FocusGuard.suspended = true; }
        function resume(): void { FocusGuard.suspended = false; }
    }

    IpcHandler {
        target: "launcher"
        function toggle(): void {
            if (localLauncher.visible)
                localLauncher.visible = false;
            else
                localLauncher.open("local");
        }
        function remote(): void {
            remoteLauncher.open("hosts");
        }
        function tools(): void {
            if (toolsLauncher.visible)
                toolsLauncher.visible = false;
            else
                toolsLauncher.open("tools");
        }
        function failure(message: string): void {
            remoteLauncher.error = message;
            remoteLauncher.visible = true;
        }
    }

    IpcHandler {
        target: "wallpaper"
        function toggle(): void {
            wallpaperOverlay.toggle();
        }
        function open(): void {
            wallpaperOverlay.show();
        }
    }

    Component.onCompleted: Quickshell.execDetached(["wallpaperctl", "restore"])

    Timer {
        id: wallpaperCycle
        interval: 300000
        repeat: true
        running: true
        onTriggered: {
            if (!wallpaperOverlay.visible)
                Quickshell.execDetached(["wallpaperctl", "random"]);
        }
    }

    FileView {
        path: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state")
            + "/wallpaper/current"
        watchChanges: true
        onTextChanged: wallpaperCycle.restart()
    }

    Launcher {
        id: localLauncher
        initialMode: "local"
    }

    Launcher {
        id: remoteLauncher
        initialMode: "hosts"
    }

    Launcher {
        id: toolsLauncher
        initialMode: "tools"
    }

    // The wallpaper itself is the preview surface; the overlay only draws the
    // title and the search field. The earlier carousel UI is kept, unused, in
    // WallpaperPicker.qml.
    WallpaperOverlay {
        id: wallpaperOverlay
    }
}
