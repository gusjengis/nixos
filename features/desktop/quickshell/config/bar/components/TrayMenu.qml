import QtQuick
import Quickshell
import "../../theme"

PopupWindow {
    id: popup

    property var currentMenu: null
    property var history: []
    property string menuTitle: ""

    function show(trayItem, anchorItem) {
        currentMenu = trayItem.menu;
        history = [];
        menuTitle = trayItem.title || trayItem.tooltipTitle || "System tray";
        anchor.item = anchorItem;
        visible = true;
    }

    function enter(entry) {
        history = history.concat([currentMenu]);
        currentMenu = entry;
    }

    function back() {
        if (history.length === 0)
            return;
        currentMenu = history[history.length - 1];
        history = history.slice(0, -1);
    }

    anchor.rect.x: (anchor.item ? anchor.item.width : 0) - width
    anchor.rect.y: Theme.barPopupY(anchor.item)
    implicitWidth: 230
    implicitHeight: Math.min(360, header.height + menuList.contentHeight + 10)
    color: "transparent"
    grabFocus: true

    QsMenuOpener {
        id: opener
        menu: popup.currentMenu
    }

    Rectangle {
        anchors.fill: parent
        radius: Theme.windowRadius
        color: Theme.background
        border { width: Theme.windowBorderWidth; color: Theme.windowBorder }
    }

    Item {
        id: header
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: popup.history.length > 0 ? 29 : 0
        visible: height > 0

        Rectangle {
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: 1
            color: Theme.border
        }

        Text {
            anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
            text: "‹"
            color: Theme.accent
            font { family: Theme.fontFamily; pixelSize: 22; bold: true }
        }

        Text {
            anchors.centerIn: parent
            width: parent.width - 50
            text: "Back"
            color: Theme.text
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignHCenter
            font { family: Theme.fontFamily; pixelSize: Theme.fontSize; bold: true }
        }

        MouseArea {
            anchors.fill: parent
            enabled: popup.history.length > 0
            onClicked: popup.back()
        }
    }

    ListView {
        id: menuList
        anchors {
            left: parent.left
            right: parent.right
            top: header.bottom
            bottom: parent.bottom
            margins: 5
        }
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: opener.children

        delegate: TrayMenuItem {
            required property var modelData
            width: menuList.width
            entry: modelData
            onActivated: {
                if (entry.hasChildren)
                    popup.enter(entry);
                else {
                    entry.triggered();
                    popup.visible = false;
                }
            }
        }
    }

    Shortcut {
        sequence: "Escape"
        enabled: popup.visible
        onActivated: {
            if (popup.history.length > 0)
                popup.back();
            else
                popup.visible = false;
        }
    }
}
