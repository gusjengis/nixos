import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Wayland
import "theme"

// A workspace composition, not a screen capture: excludes the picker, dock and
// global overlays. Each window requests one frozen frame, including if hidden.
Rectangle {
    id: preview
    required property var workspace
    property var iconForWindow
    property real specialBlurRadius: 12
    property real specialDim: 0
    color: "#242b35"
    clip: true

    Item {
        id: desktop
        objectName: "session-preview-desktop"
        readonly property real ratio: preview.workspace ? Math.min(preview.width / preview.workspace.width, preview.height / preview.workspace.height) : 1
        width: preview.workspace ? preview.workspace.width * ratio : preview.width
        height: preview.workspace ? preview.workspace.height * ratio : preview.height
        anchors.centerIn: parent
        // Supersample composition edges, then filter down to the card size.
        layer.enabled: true
        layer.textureSize: Qt.size(Math.max(1, Math.ceil(width * 2)), Math.max(1, Math.ceil(height * 2)))
        layer.smooth: true
        layer.mipmap: true

        // Wallpaper and windows share one monitor-shaped canvas. Spare space
        // outside it must not look like uncovered desktop beside a fullscreen app.
        Item {
            id: background
            objectName: "session-preview-background"
            anchors.fill: parent
            layer.enabled: !!preview.workspace && !!preview.workspace.special && preview.specialBlurRadius > 0
            layer.effect: MultiEffect {
                objectName: "session-preview-background-blur"
                blurEnabled: true
                blurMax: 64
                blur: Math.min(1, preview.specialBlurRadius * desktop.ratio / 64)
                autoPaddingEnabled: false
            }
            Image {
                objectName: "session-preview-wallpaper"
                anchors.fill: parent
                source: Theme.wallpaperPath ? "file://" + Theme.wallpaperPath : ""
                sourceSize.width: Math.max(1, Math.ceil(desktop.width * 2))
                smooth: true
                mipmap: true
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
            }
            Repeater {
                model: preview.workspace ? (preview.workspace.backgroundWindows || []) : []
                PreviewWindow {}
            }
        }
        Rectangle {
            objectName: "session-preview-special-dim"
            anchors.fill: parent
            visible: !!preview.workspace && !!preview.workspace.special
            color: "black"
            opacity: preview.specialDim
        }

        Repeater {
            model: preview.workspace ? preview.workspace.windows : []
            PreviewWindow {}
        }
    }
    component PreviewWindow: Rectangle {
        id: window
        objectName: "session-preview-window"
        required property var modelData
        readonly property var icon: preview.iconForWindow ? preview.iconForWindow(modelData) : ""
        x: ((modelData.at || [0, 0])[0] - preview.workspace.x) * desktop.ratio
        y: ((modelData.at || [0, 0])[1] - preview.workspace.y) * desktop.ratio
        width: Math.max(4, (modelData.size || [800, 600])[0] * desktop.ratio)
        height: Math.max(4, (modelData.size || [800, 600])[1] * desktop.ratio)
        radius: 3
        antialiasing: true
        color: "#ec303238"
        border { width: 1; color: "#50ffffff" }
        clip: true
        Image {
            anchors.centerIn: parent
            width: Math.min(40, parent.width * 0.5)
            height: width
            source: window.icon
            visible: !capture.hasContent
        }
        ScreencopyView {
            id: capture
            objectName: "session-window-capture"
            anchors.fill: parent
            captureSource: window.modelData.captureSource || null
            live: false
            paintCursor: false
            // constraintSize only controls implicit geometry, not capture pixels.
            // Generate mip levels at native capture resolution before shrinking:
            // direct bilinear minification skips thin lines and aliases text.
            layer.enabled: hasContent
            layer.textureSize: sourceSize
            layer.smooth: true
            layer.mipmap: true
        }
    }
    Text {
        anchors.centerIn: parent
        visible: !preview.workspace
        text: "No open windows"
        color: "#99ffffff"
        font { family: Theme.fontFamily; pixelSize: 13 }
    }
}
