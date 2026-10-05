import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import "../../state"
import "../../theme"

// Menu-bar dropdown. It is a layer surface rather than an xdg popup because
// the compositor's Liquid Glass (hyprglass) only renders behind layer
// surfaces. The surface is padded on every side so the compositor can draw
// the glass drop shadow; only the popup body accepts input.
PanelWindow {
    id: popup

    // Item the dropdown hangs from and the body's offset relative to it,
    // equivalent to PopupWindow's anchor.item / anchor.rect.
    property Item anchorItem: null
    property real popupX: 0
    property real popupY: Theme.barPopupY(anchorItem)
    property real popupWidth: 200
    property real popupHeight: 100
    // Must match the hyprglass layer radius configured for glassNamespace.
    property string glassNamespace: "quickshell-menu"
    // False for surfaces whose children carry their own material.
    property bool backgroundVisible: true
    property bool acceptsInput: true
    property bool focusGrabEnabled: true
    property var focusWindows: [popup]
    property int popupRadius: glassNamespace === "quickshell-panel" ? Theme.panelRadius : Theme.menuRadius
    readonly property bool glass: Theme.glassActive
    property int shadowPadding: glass ? Theme.glassShadowPadding : 0
    default property alias content: body.data
    readonly property Item body: body

    property point _origin: Qt.point(0, 0)

    function _place() {
        if (!anchorItem)
            return;
        const p = anchorItem.mapToItem(null, popupX, popupY);
        const maxX = screen ? screen.width - popupWidth - Theme.popupScreenMargin : p.x;
        _origin = Qt.point(Math.round(Math.max(Theme.popupScreenMargin, Math.min(p.x, maxX))), Math.round(p.y));
    }

    onVisibleChanged: if (visible) _place()
    onAnchorItemChanged: _place()
    onPopupXChanged: _place()
    onPopupWidthChanged: _place()
    onPopupYChanged: _place()
    onScreenChanged: _place()

    visible: false
    screen: anchorItem && anchorItem.QsWindow.window ? anchorItem.QsWindow.window.screen : null
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    implicitWidth: popupWidth + 2 * shadowPadding
    implicitHeight: popupHeight + 2 * shadowPadding
    anchors {
        top: true
        left: true
    }
    margins {
        left: _origin.x - shadowPadding
        top: _origin.y - shadowPadding
    }
    WlrLayershell.namespace: glassNamespace
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: visible ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None
    mask: Region {
        item: popup.acceptsInput ? frame : null
        width: 0
        height: 0
    }

    HyprlandFocusGrab {
        active: popup.visible && popup.focusGrabEnabled && !FocusGuard.suspended
        windows: popup.focusWindows
        onCleared: {
            if (!FocusGuard.suspended)
                popup.visible = false;
        }
    }

    Item {
        id: frame
        x: popup.shadowPadding
        y: popup.shadowPadding
        width: popup.popupWidth
        height: popup.popupHeight

        // Without compositor glass, fall back to an opaque dark material.
        Rectangle {
            anchors.fill: parent
            visible: !popup.glass && popup.backgroundVisible
            radius: popup.popupRadius
            color: Theme.background
            border { width: 1; color: Theme.windowBorder }
        }

        Item {
            id: body
            anchors.fill: parent
        }
    }
}
