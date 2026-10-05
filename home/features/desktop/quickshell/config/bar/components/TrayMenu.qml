import QtQuick
import Quickshell
import "../../theme"
import "../../widgets"

GuardedPopupWindow {
    id: popup

    property var currentMenu: null
    property var history: []
    property string menuTitle: ""

    function show(trayItem, anchorItem) {
        currentMenu = trayItem.menu;
        history = [];
        menuTitle = trayItem.title || trayItem.tooltipTitle || "System tray";
        popup.anchorItem = anchorItem;
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

    readonly property bool reserveLeading: {
        const entries = opener.children ? opener.children.values : [];
        return entries.some(entry => entry && !entry.isSeparator && (entry.buttonType !== QsMenuButtonType.None || entry.icon !== ""));
    }

    popupX: (anchorItem ? anchorItem.width : 0) - popupWidth
    popupWidth: 240
    popupHeight: Math.min(560, header.height + menuList.contentHeight + 2 * Theme.menuPadding)

    QsMenuOpener {
        id: opener
        menu: popup.currentMenu
    }

    // Submenus open in place (no cascading surface); this row returns.
    Item {
        id: header
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: Theme.menuPadding }
        height: popup.history.length > 0 ? Theme.menuRowHeight + Theme.menuSeparatorHeight : 0
        visible: height > 0

        Rectangle {
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: Theme.menuRowHeight
            radius: Theme.menuHighlightRadius
            color: backMouse.containsMouse ? Theme.menuHighlight : "transparent"

            SFSymbol {
                id: backChevron
                anchors { left: parent.left; leftMargin: Theme.menuTextInset - Theme.menuPadding; verticalCenter: parent.verticalCenter }
                symbol: "chevron.left"
                size: 11
                color: backMouse.containsMouse ? "#ffffff" : Theme.menuText
            }

            Text {
                anchors { left: backChevron.right; leftMargin: 8; verticalCenter: parent.verticalCenter }
                text: "Back"
                color: backMouse.containsMouse ? "#ffffff" : Theme.menuText
                font { family: Theme.fontFamily; pixelSize: Theme.menuFontSize }
            }

            MouseArea {
                id: backMouse
                anchors.fill: parent
                hoverEnabled: true
                enabled: popup.history.length > 0
                onClicked: popup.back()
            }
        }

        Rectangle {
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom; bottomMargin: (Theme.menuSeparatorHeight - 1) / 2
                leftMargin: Theme.menuTextInset - Theme.menuPadding; rightMargin: Theme.menuTextInset - Theme.menuPadding }
            height: 1
            color: Theme.menuSeparator
        }
    }

    ListView {
        id: menuList
        anchors {
            left: parent.left
            right: parent.right
            top: header.visible ? header.bottom : parent.top
            bottom: parent.bottom
            margins: Theme.menuPadding
            topMargin: header.visible ? 0 : Theme.menuPadding
        }
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: opener.children

        delegate: TrayMenuItem {
            required property var modelData
            width: menuList.width
            entry: modelData
            reserveLeading: popup.reserveLeading
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
