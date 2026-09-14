import QtQuick
import QtQuick.Controls
import QtQuick.Shapes
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import "theme"

PanelWindow {
    id: picker

    visible: false
    focusable: true
    exclusionMode: ExclusionMode.Ignore
    implicitWidth: screen.width * 0.5
    implicitHeight: screen.height / 3
    color: "transparent"
    WlrLayershell.namespace: "quickshell-wallpaper-picker"

    property var wallpapers: []
    property real animatedIndex: 0
    property string originalWallpaper: ""
    property bool ready: false
    readonly property int selectedIndex: {
        if (wallpapers.length === 0)
            return 0;
        const index = Math.round(animatedIndex) % wallpapers.length;
        return index < 0 ? index + wallpapers.length : index;
    }

    function show() {
        ready = false;
        const focusedMonitor = Hyprland.focusedMonitor;
        if (focusedMonitor) {
            for (let index = 0; index < Quickshell.screens.length; index++) {
                const candidate = Quickshell.screens[index];
                if (candidate.name === focusedMonitor.name) {
                    screen = candidate;
                    break;
                }
            }
        }
        visible = true;
        if (!catalog.running)
            catalog.running = true;
    }

    function toggle() {
        if (visible)
            dismiss();
        else
            show();
    }

    function dismiss() {
        applySelected();
    }

    function restoreOriginal() {
        previewTimer.stop();
        if (originalWallpaper !== "")
            Quickshell.execDetached(["wallpaperctl", "set", originalWallpaper]);
        visible = false;
    }

    function select(offset) {
        if (wallpapers.length === 0)
            return;
        animatedIndex = Math.round(animatedIndex) + offset;
    }

    function applySelected() {
        if (wallpapers.length === 0) {
            visible = false;
            return;
        }
        previewTimer.stop();
        Quickshell.execDetached(["wallpaperctl", "set", wallpapers[selectedIndex].path]);
        visible = false;
    }

    function selectRandom() {
        if (wallpapers.length === 0)
            return;
        animatedIndex = Math.floor(Math.random() * wallpapers.length);
    }

    onSelectedIndexChanged: {
        if (!visible || !ready || wallpapers.length === 0)
            return;
        previewTimer.path = wallpapers[selectedIndex].path;
        previewTimer.restart();
    }

    onVisibleChanged: {
        focusGrab.active = visible;
        if (visible)
            keyHandler.forceActiveFocus();
    }

    HyprlandFocusGrab {
        id: focusGrab
        windows: [picker]
        onCleared: picker.dismiss()
    }

    Process {
        id: catalog
        command: ["wallpaperctl", "catalog"]
        stdout: StdioCollector { id: catalogOutput }
        onExited: (code, status) => {
            if (code !== 0 || status !== 0)
                return;
            try {
                const result = JSON.parse(catalogOutput.text);
                picker.wallpapers = result.wallpapers || [];
                picker.originalWallpaper = result.current || "";
                let activeIndex = picker.wallpapers.findIndex(item => item.path === picker.originalWallpaper);
                picker.animatedIndex = activeIndex >= 0 ? activeIndex : 0;
                Qt.callLater(() => picker.ready = true);
            } catch (error) {
                console.warn("Cannot load wallpaper catalog:", error);
            }
        }
    }

    Timer {
        id: previewTimer
        property string path: ""
        interval: 120
        onTriggered: {
            if (picker.visible && path !== "")
                Quickshell.execDetached(["wallpaperctl", "preview", path]);
        }
    }

    Behavior on animatedIndex {
        enabled: picker.ready
        NumberAnimation { duration: 190; easing.type: Easing.OutCubic }
    }

    Shortcut { sequence: "Left"; enabled: picker.visible; onActivated: picker.select(-1) }
    Shortcut { sequence: "Right"; enabled: picker.visible; onActivated: picker.select(1) }
    Shortcut { sequence: "H"; enabled: picker.visible; onActivated: picker.select(-1) }
    Shortcut { sequence: "L"; enabled: picker.visible; onActivated: picker.select(1) }
    Shortcut { sequence: "A"; enabled: picker.visible; onActivated: picker.select(-1) }
    Shortcut { sequence: "D"; enabled: picker.visible; onActivated: picker.select(1) }
    Shortcut { sequence: "R"; enabled: picker.visible; onActivated: picker.selectRandom() }
    Shortcut { sequence: "Return"; enabled: picker.visible; onActivated: picker.applySelected() }
    Shortcut { sequence: "Space"; enabled: picker.visible; onActivated: picker.applySelected() }
    Shortcut { sequence: "Escape"; enabled: picker.visible; onActivated: picker.applySelected() }
    Shortcut { sequence: "Q"; enabled: picker.visible; onActivated: picker.applySelected() }
    Shortcut { sequence: "Backspace"; enabled: picker.visible; onActivated: picker.restoreOriginal() }

    Item {
        id: keyHandler
        anchors.fill: parent
        focus: true
    }

    Item {
        id: stage
        anchors.fill: parent

        Text {
            anchors.centerIn: parent
            visible: picker.wallpapers.length === 0
            text: catalog.running ? "Loading wallpapers..." : "No wallpapers found in ~/Wallpapers"
            color: Theme.muted
            font.pixelSize: 14
        }

        Item {
            id: carousel
            anchors.fill: parent
            clip: true

            Repeater {
                model: 11

                delegate: Item {
                    id: card

                    readonly property int count: picker.wallpapers.length
                    readonly property int rawIndex: Math.floor((picker.animatedIndex - index + 5.5) / 11) * 11 + index
                    readonly property int wallpaperIndex: count === 0 ? 0 : ((rawIndex % count) + count) % count
                    readonly property var wallpaper: count === 0 ? null : picker.wallpapers[wallpaperIndex]
                    readonly property real distance: rawIndex - picker.animatedIndex
                    readonly property real absoluteDistance: Math.abs(distance)
                    readonly property real centerProgress: Math.sin(Math.max(0, 1 - Math.min(1, absoluteDistance)) * Math.PI / 2)
                    readonly property bool centered: absoluteDistance < 0.5
                    readonly property real cardWidth: carousel.width * (0.05 + centerProgress * 0.43)
                    readonly property real step: absoluteDistance <= 1
                        ? distance * carousel.width * 0.3
                        : (distance < 0 ? -1 : 1) * carousel.width * (0.3 + (absoluteDistance - 1) * 0.055)

                    width: cardWidth
                    height: carousel.height * 0.88
                    x: carousel.width / 2 - width / 2 + step
                    y: carousel.height / 2 - height / 2
                    z: 100 - Math.round(absoluteDistance * 10)
                    opacity: Math.max(0, 1 - absoluteDistance / 5.5)
                    visible: count > 0 && opacity > 0

                    transform: Matrix4x4 {
                        matrix: Qt.matrix4x4(
                            1, -0.16, 0, 0,
                            0, 1, 0, 0,
                            0, 0, 1, 0,
                            0, 0, 0, 1
                        )
                    }

                    Rectangle {
                        id: cardSource
                        anchors.fill: parent
                        color: Theme.background
                        visible: false
                        layer.enabled: true
                        layer.smooth: true

                        Image {
                            x: -height * 0.16
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            width: parent.width + height * 0.16
                            source: card.wallpaper ? "file://" + card.wallpaper.path : ""
                            sourceSize.width: 1200
                            sourceSize.height: 700
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                            cache: true

                            // Counter-transform image pixels while the shape keeps slanted edges.
                            transform: Matrix4x4 {
                                matrix: Qt.matrix4x4(
                                    1, 0.16, 0, 0,
                                    0, 1, 0, 0,
                                    0, 0, 1, 0,
                                    0, 0, 0, 1
                                )
                            }
                        }
                    }

                    Shape {
                        anchors.fill: parent
                        preferredRendererType: Shape.CurveRenderer

                        ShapePath {
                            strokeWidth: -1
                            fillItem: cardSource
                            pathHints: ShapePath.PathLinear | ShapePath.PathConvex | ShapePath.PathSolid

                            PathRectangle {
                                width: card.width
                                height: card.height
                            }
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        property real pressX: 0
                        property real startIndex: 0
                        property bool dragged: false

                        onPressed: mouse => {
                            pressX = card.mapToItem(stage, mouse.x, mouse.y).x;
                            startIndex = picker.animatedIndex;
                            dragged = false;
                        }
                        onPositionChanged: mouse => {
                            if (!pressed)
                                return;
                            const position = card.mapToItem(stage, mouse.x, mouse.y).x;
                            if (Math.abs(position - pressX) > 8)
                                dragged = true;
                            if (dragged)
                                picker.animatedIndex = startIndex - (position - pressX) / 145;
                        }
                        onReleased: {
                            if (dragged)
                                picker.animatedIndex = Math.round(picker.animatedIndex);
                        }
                        onClicked: {
                            if (dragged)
                                return;
                            if (card.centered)
                                picker.applySelected();
                            else
                                picker.animatedIndex = card.rawIndex;
                        }
                        onWheel: wheel => picker.select(wheel.angleDelta.y < 0 ? 1 : -1)
                    }
                }
            }
        }
    }
}
