import QtQuick
import QtQuick.Shapes
import Quickshell
import Quickshell.Wayland
import "theme"

// Measured macOS label: 26 px capsule and a rounded 7 px pointer, 2 px above
// the Dock. hyprglass renders both as one silhouette, including the pointer's
// backdrop, refraction and rim. The client only supplies text (or a fallback).
PanelWindow {
    id: tip

    property string text: ""
    property real centerX: 0     // screen x of the hovered icon centre
    property int dockBottom: 94  // screen bottom to Dock body top
    property bool shown: false
    // Hidden while a Dock menu is open, as on macOS.
    property bool suppressed: false
    property var hoveredItem: null
    onHoveredItemChanged: if (!hoveredItem) shown = false
    readonly property int pad: Theme.glassShadowPadding
    readonly property int bodyHeight: 26
    readonly property int pointerHeight: 7
    readonly property int bodyWidth: Math.ceil(label.implicitWidth) + 26

    function setHovered(item, name, hovered, x) {
        if (hovered) {
            hoveredItem = item;
            text = name;
            centerX = x;
            shown = true;
        } else if (hoveredItem === item) {
            shown = false;
            hoveredItem = null;
        }
    }

    visible: shown && !suppressed && text !== ""
    color: "transparent"
    focusable: false
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "quickshell-dock-tip"
    WlrLayershell.layer: WlrLayer.Overlay
    anchors { left: true; bottom: true }
    implicitWidth: bodyWidth + 2 * pad
    implicitHeight: bodyHeight + pointerHeight + 2 * pad
    margins.left: Math.round(centerX - bodyWidth / 2) - pad
    margins.bottom: dockBottom + 2 - pad
    mask: Region {}

    Rectangle {
        // Fallback body when the compositor glass is unavailable.
        x: tip.pad
        y: tip.pad
        width: tip.bodyWidth
        height: tip.bodyHeight
        radius: height / 2
        visible: !Theme.glassActive
        color: "#b8363636"
    }

    // Fallback uses the same rounded shoulders/tip as the compositor shape.
    Shape {
        visible: !Theme.glassActive
        x: tip.pad + tip.bodyWidth / 2 - 15
        y: tip.pad + tip.bodyHeight - 1
        width: 30
        height: tip.pointerHeight + 1
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            fillColor: "#b8363636"
            strokeWidth: -1
            startX: 0; startY: 1
            PathLine { x: 30; y: 1 }
            PathCubic { x: 17; y: 7; control1X: 24; control1Y: 1; control2X: 23; control2Y: 3 }
            PathQuad { x: 13; y: 7; controlX: 15; controlY: 9 }
            PathCubic { x: 0; y: 1; control1X: 7; control1Y: 3; control2X: 6; control2Y: 1 }
        }
    }

    DockLabel {
        id: label
        x: tip.pad + 13
        y: tip.pad + 18 - baselineOffset
        text: tip.text
    }
}
