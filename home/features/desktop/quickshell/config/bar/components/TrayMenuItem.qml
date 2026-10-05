import QtQuick
import Quickshell
import Quickshell.Widgets
import "../../theme"
import "../../widgets"

// macOS 27 menu row: 24px item with a blue rounded highlight, or an 11px
// separator. `reserveLeading` indents titles when any row in the menu shows a
// checkmark or icon, as AppKit does.
Item {
    id: row

    required property var entry
    property bool reserveLeading: false
    readonly property bool highlighted: !!entry && !entry.isSeparator && entry.enabled && mouse.containsMouse
    readonly property color textColor: highlighted ? "#ffffff" : entry && entry.enabled ? Theme.menuText : Theme.menuSecondaryText
    signal activated()

    // D-Bus menu entries can disappear before their delegates are destroyed.
    visible: !!entry
    implicitHeight: !entry ? 0 : entry.isSeparator ? Theme.menuSeparatorHeight : Theme.menuRowHeight

    Rectangle {
        visible: !!row.entry && row.entry.isSeparator
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter
            leftMargin: Theme.menuTextInset - Theme.menuPadding; rightMargin: Theme.menuTextInset - Theme.menuPadding }
        height: 1
        color: Theme.menuSeparator
    }

    Rectangle {
        anchors.fill: parent
        visible: row.highlighted
        radius: Theme.menuHighlightRadius
        color: Theme.menuHighlight
    }

    SFSymbol {
        visible: !!row.entry && !row.entry.isSeparator && row.entry.buttonType !== QsMenuButtonType.None && row.entry.checkState === Qt.Checked
        anchors { left: parent.left; leftMargin: Theme.menuTextInset - Theme.menuPadding; verticalCenter: parent.verticalCenter }
        symbol: "checkmark"
        size: 12
        color: row.textColor
    }

    IconImage {
        visible: !!row.entry && !row.entry.isSeparator && row.entry.icon !== "" && row.entry.buttonType === QsMenuButtonType.None
        anchors { left: parent.left; leftMargin: Theme.menuTextInset - Theme.menuPadding; verticalCenter: parent.verticalCenter }
        implicitSize: 15
        source: row.entry ? row.entry.icon : ""
    }

    Text {
        visible: !!row.entry && !row.entry.isSeparator
        anchors {
            left: parent.left
            leftMargin: Theme.menuTextInset - Theme.menuPadding + (row.reserveLeading ? 22 : 0)
            right: arrow.left
            rightMargin: 8
            verticalCenter: parent.verticalCenter
        }
        text: row.entry ? row.entry.text.replace(/&(?!&)/g, "") : ""
        color: row.textColor
        elide: Text.ElideRight
        font { family: Theme.fontFamily; pixelSize: Theme.menuFontSize }
    }

    SFSymbol {
        id: arrow
        visible: !!row.entry && !row.entry.isSeparator && row.entry.hasChildren
        anchors { right: parent.right; rightMargin: Theme.menuTextInset - Theme.menuPadding; verticalCenter: parent.verticalCenter }
        symbol: "chevron.right"
        size: 11
        color: row.textColor
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        enabled: !!row.entry && !row.entry.isSeparator && row.entry.enabled
        onClicked: row.activated()
    }
}
