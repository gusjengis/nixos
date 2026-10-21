import QtQuick
import QtQuick.Controls
import Quickshell.Io
import "theme"

Rectangle {
    id: root
    property string directory: ""
    property string configuredDirectory: directory
    property string targetDirectory: directory
    property bool directoryAvailable: true
    property bool editable: false
    signal editRequested()
    property bool active: true
    property string listing: ""
    property string requestDirectory: ""

    color: "#212630"
    border.color: "#393f4c"

    function refresh() {
        listing = active && directory ? "Loading…" : "Select a context to preview its working directory.";
        delay.restart();
    }
    onDirectoryChanged: refresh()
    onActiveChanged: refresh()

    // Debounce navigation; a completed request can only publish for its own path.
    Timer {
        id: delay
        interval: 120
        onTriggered: {
            if (!root.active || !root.directory || process.running) return;
            root.requestDirectory = root.directory;
            process.command = ["ls", "-al", "--color=never", "--", root.requestDirectory];
            process.running = true;
        }
    }
    Process {
        id: process
        stdout: StdioCollector { id: output }
        stderr: StdioCollector { id: errors }
        onExited: (code, status) => {
            if (!root.active) return;
            if (root.requestDirectory !== root.directory) { delay.restart(); return; }
            root.listing = code === 0 && status === 0 ? output.text : errors.text.trim() || "Cannot read this directory.";
        }
    }

    Text {
        id: heading
        anchors.top: parent.top; anchors.topMargin: 18
        anchors.left: parent.left; anchors.leftMargin: 17
        text: "WORKING DIRECTORY"
        color: "#9caac0"
        font { family: Theme.fontFamily; pixelSize: 11; weight: Font.DemiBold; letterSpacing: 1.3 }
    }
    Text {
        id: path
        anchors.top: heading.bottom; anchors.topMargin: 10
        anchors.left: parent.left; anchors.leftMargin: 17
        anchors.right: parent.right; anchors.rightMargin: 17
        text: (root.configuredDirectory || "No context selected") + (root.editable ? "  ✎" : "")
        textFormat: Text.PlainText
        wrapMode: Text.WrapAnywhere
        color: root.editable ? "#a4c4ee" : "#d4ddec"
        font { family: Theme.fontFamily; pixelSize: 13 }
        MouseArea {
            anchors.fill: parent
            enabled: root.editable
            cursorShape: Qt.PointingHandCursor
            onClicked: root.editRequested()
        }
    }
    Text {
        id: resolvedPath
        anchors.top: path.bottom; anchors.topMargin: 8
        anchors.left: parent.left; anchors.leftMargin: 17
        anchors.right: parent.right; anchors.rightMargin: 17
        text: !root.directoryAvailable ? "Unavailable: " + root.targetDirectory + "\nUsing context folder: " + root.directory
            : root.configuredDirectory !== root.targetDirectory ? root.targetDirectory : ""
        visible: !!text
        textFormat: Text.PlainText
        wrapMode: Text.WrapAnywhere
        color: root.directoryAvailable ? "#9caac0" : "#edc58a"
        font { family: Theme.fontFamily; pixelSize: 12 }
    }
    Flickable {
        anchors.top: resolvedPath.visible ? resolvedPath.bottom : path.bottom; anchors.topMargin: 14
        anchors.bottom: parent.bottom
        anchors.left: parent.left; anchors.right: parent.right
        clip: true
        contentWidth: Math.max(width, listingText.implicitWidth + 34)
        contentHeight: Math.max(height, listingText.implicitHeight + 25)
        boundsBehavior: Flickable.StopAtBounds
        onContentHeightChanged: { contentX = 0; contentY = 0; }
        ScrollBar.vertical: ScrollBar {}
        ScrollBar.horizontal: ScrollBar {}
        Text {
            id: listingText
            x: 17; y: 5
            text: root.listing
            textFormat: Text.PlainText
            color: "#b9c6d9"
            font { family: "monospace"; pixelSize: 12 }
        }
    }
}
