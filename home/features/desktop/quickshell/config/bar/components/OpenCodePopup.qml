import QtQuick
import "../../theme"

// This surface stays instantiated. Kitty's headless rasterizer prepares real
// terminal pixels in the background; opening only maps this cached popup.
GuardedPopupWindow {
    id: popup
    required property var service
    readonly property int borderSize: Theme.windowBorderWidth
    readonly property int headerPadding: 12
    readonly property bool contentReady: canvas.readyImage !== "" && wordmark.status === Image.Ready
    property real openedAt: 0
    property real firstPaintMs: -1
    function toggle(item) {
        if (visible) { visible = false; return; }
        anchorItem = item;
        openedAt = Date.now();
        firstPaintMs = -1;
        visible = true;
        canvas.requestPaint();
    }
    function sessionAt(y) {
        const row = Math.floor(y / service.cellHeight);
        const index = service.offset + Math.floor((row - 3) / 4);
        return row >= 3 && row < canvas.height / service.cellHeight - 1
            && index >= 0 && index < service.sessions.length ? index : -1;
    }
    function activate(index) {
        const session = service.sessions[index];
        if (session) { visible = false; service.focus(session.pane); }
    }
    function handleKey(key) {
        if (key === Qt.Key_Up || key === Qt.Key_Down)
            service.moveSelection(key === Qt.Key_Up ? -1 : 1);
        else if (key === Qt.Key_PageUp || key === Qt.Key_PageDown)
            service.moveSelection((key === Qt.Key_PageUp ? -1 : 1) * service.pageSize);
        else if (key === Qt.Key_Return || key === Qt.Key_Enter) activate(Math.max(0, service.selected));
        else if (key === Qt.Key_Escape) visible = false;
        else return false;
        return true;
    }
    onVisibleChanged: {
        if (visible) {
            service.showPanel(popup);
            Qt.callLater(() => canvas.forceActiveFocus());
        } else service.hidePanel(popup);
    }
    glassNamespace: "quickshell-opencode-terminal"
    shadowPadding: 0
    backgroundVisible: false
    popupRadius: Theme.windowRadius
    popupX: (anchorItem ? anchorItem.width : 0) - popupWidth
    popupWidth: service.bitmapWidth + 2 * borderSize
    popupHeight: service.bitmapHeight + headerPadding + 2 * borderSize

    Rectangle {
        anchors.fill: parent
        radius: popup.popupRadius
        color: "#0d1117"
        border { width: popup.borderSize; color: Theme.windowBorder }
    }
    Canvas {
        id: canvas
        x: popup.borderSize
        y: popup.borderSize + popup.headerPadding
        width: popup.service.bitmapWidth
        height: popup.service.bitmapHeight
        property string pendingImage: ""
        property string readyImage: ""
        focus: true
        function loadFrame() {
            if (!popup.service.bitmapPath) return;
            // Canvas unloadImage clears its local entry, not Qt's shared
            // URL-keyed pixmap cache. The files are reused; their URLs cannot be.
            pendingImage = "file://" + popup.service.bitmapPath + "?frame=" + popup.service.bitmapGeneration;
            loadImage(pendingImage);
        }
        Component.onCompleted: loadFrame()
        Connections {
            target: popup.service
            function onBitmapGenerationChanged() { canvas.loadFrame(); }
        }
        onImageLoaded: {
            if (!isImageLoaded(pendingImage)) return;
            const previous = readyImage;
            readyImage = pendingImage;
            requestPaint();
            if (previous && previous !== readyImage) unloadImage(previous);
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            const ctx = getContext("2d");
            ctx.reset();
            ctx.clearRect(0, 0, width, height);
            if (!readyImage || !isImageLoaded(readyImage)) return;
            const r = Math.max(0, popup.popupRadius - popup.borderSize);
            ctx.beginPath();
            ctx.moveTo(r, 0);
            ctx.arcTo(width, 0, width, height, r);
            ctx.arcTo(width, height, 0, height, r);
            ctx.arcTo(0, height, 0, 0, r);
            ctx.arcTo(0, 0, width, 0, r);
            ctx.closePath();
            ctx.clip();
            ctx.imageSmoothingEnabled = false;
            ctx.drawImage(readyImage, 0, 0);
            if (popup.visible && popup.firstPaintMs < 0) popup.firstPaintMs = Date.now() - popup.openedAt;
        }
        Keys.onPressed: event => { event.accepted = popup.handleKey(event.key); }
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: popup.service.selected >= 0 ? Qt.PointingHandCursor : Qt.ArrowCursor
            onPositionChanged: mouse => popup.service.selected = popup.sessionAt(mouse.y)
            onExited: popup.service.selected = -1
            onClicked: mouse => popup.activate(popup.sessionAt(mouse.y))
        }
    }
    Image {
        id: wordmark
        // Official artwork sits above the cell grid. Its six-unit blocks map
        // to four whole pixels at this size, preserving the pixel-cut edges.
        source: "icons/opencode-wordmark-dark.svg"
        anchors.horizontalCenter: parent.horizontalCenter
        y: popup.borderSize + 4 + popup.headerPadding / 2
        width: 156
        height: 28
        sourceSize: Qt.size(width, height)
        fillMode: Image.PreserveAspectFit
        smooth: false
    }
}
