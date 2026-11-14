import QtQuick
import Quickshell
import Quickshell.Widgets
import "../theme"
import "../widgets"

// macOS 27 menu row: 24px item with a blue rounded highlight, or an 11px
// separator. AppKit reserves a shared state column for checks; icons occupy
// their own column on rows that supply one.
Item {
    id: row

    required property var entry
    property bool reserveLeading: false
    property bool keyboardHighlighted: false
    property bool stripMnemonics: true
    property font textFont: Theme.menuFont
    property int textRenderType: Text.NativeRendering
    readonly property bool highlighted: !!entry && !entry.isSeparator && entry.enabled && keyboardHighlighted
    // Keep glyph ink identical across selection; only the background changes.
    readonly property color textColor: entry && entry.enabled ? "#ffffff" : Theme.menuSecondaryText
    signal activated()
    signal hovered()
    signal hoverEnded()

    // D-Bus menu entries can disappear before their delegates are destroyed.
    visible: !!entry
    implicitHeight: !entry ? 0 : entry.isSeparator ? Theme.menuSeparatorHeight : Theme.menuRowHeight

    Rectangle {
        visible: !!row.entry && !!row.entry.isSeparator
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter
            leftMargin: Theme.menuTextInset - Theme.menuPadding + (row.reserveLeading ? 14 : 0); rightMargin: Theme.menuTextInset - Theme.menuPadding }
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
        anchors { left: parent.left; leftMargin: Theme.menuTextInset - Theme.menuPadding - 2; verticalCenter: parent.verticalCenter }
        symbol: "checkmark"
        size: 12
        color: row.textColor
    }

    IconImage {
        visible: !!row.entry && !row.entry.isSeparator && !!row.entry.icon
        anchors { left: parent.left; leftMargin: Theme.menuTextInset - Theme.menuPadding + (row.reserveLeading ? 14 : 0); verticalCenter: parent.verticalCenter }
        implicitSize: 15
        source: row.entry && row.entry.icon || ""
    }

    Text {
        objectName: "context-menu-label"
        visible: !!row.entry && !row.entry.isSeparator
        anchors {
            left: parent.left
            leftMargin: Theme.menuTextInset - Theme.menuPadding + (row.reserveLeading ? 14 : 0) + (row.entry && row.entry.icon ? 21 : 0)
            right: shortcut.left
            rightMargin: row.entry && row.entry.shortcut ? 8 : 0
            verticalCenter: parent.verticalCenter
        }
        text: !row.entry ? "" : row.stripMnemonics ? row.entry.text.replace(/&&/g, "\u0000").replace(/&/g, "").replace(/\u0000/g, "&") : row.entry.text
        textFormat: Text.PlainText
        color: row.textColor
        elide: Text.ElideRight
        font: row.textFont
        renderType: row.textRenderType
    }

    Text {
        id: shortcut
        anchors { right: arrow.left; rightMargin: row.entry && row.entry.shortcut ? 8 : 0; verticalCenter: parent.verticalCenter }
        text: row.entry && row.entry.shortcut || ""
        textFormat: Text.PlainText
        color: row.highlighted ? "white" : Theme.menuSecondaryText
        font: row.textFont
        renderType: row.textRenderType
    }

    SFSymbol {
        id: arrow
        width: visible ? 11 : 0
        visible: !!row.entry && !row.entry.isSeparator && !!row.entry.hasChildren
        anchors { right: parent.right; rightMargin: Theme.menuTextInset - Theme.menuPadding; verticalCenter: parent.verticalCenter }
        symbol: "chevron.right"
        size: 11
        color: row.textColor
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        enabled: !!row.entry && !row.entry.isSeparator && !!row.entry.enabled
        onClicked: row.activated()
        onEntered: row.hovered()
        onExited: row.hoverEnded()
    }
}
