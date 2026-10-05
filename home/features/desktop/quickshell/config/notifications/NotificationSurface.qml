import QtQuick
import Quickshell
import Quickshell.Wayland

// Runtime profile: quickshell-notification-card, radius 22, inset 80.
// Placement describes the actual card body, not the padded layer surface.
PanelWindow {
    id: root

    property real bodyX: 0
    property real bodyY: 0
    property real bodyWidth: 372
    property real bodyHeight: 80
    property bool keyboardEnabled: false
    readonly property int shadowPadding: 80
    readonly property int cardRadius: 22
    readonly property int overhang: 8
    default property alias content: body.data

    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    implicitWidth: bodyWidth + 2 * shadowPadding
    implicitHeight: bodyHeight + 2 * shadowPadding
    anchors { top: true; left: true }
    margins { left: Math.round(bodyX) - shadowPadding; top: Math.round(bodyY) - shadowPadding }
    WlrLayershell.namespace: "quickshell-notification-card"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: keyboardEnabled && visible ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None
    mask: Region { item: inputArea }

    Item {
        id: inputArea
        x: root.shadowPadding - root.overhang
        y: root.shadowPadding - root.overhang
        width: root.bodyWidth + root.overhang
        height: root.bodyHeight + root.overhang
    }

    Item {
        id: body
        x: root.shadowPadding
        y: root.shadowPadding
        width: root.bodyWidth
        height: root.bodyHeight
    }
}
