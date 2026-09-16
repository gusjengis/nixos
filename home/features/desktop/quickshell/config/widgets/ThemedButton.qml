import QtQuick
import QtQuick.Controls
import "../theme"

Button {
    id: control

    // "normal" | "accent" | "danger" | "ghost"
    property string variant: "normal"
    property string iconText: ""
    property int iconSize: Theme.fontSize + 3

    readonly property color tint: variant === "accent" ? Theme.accentStrong
        : variant === "danger" ? Theme.danger
        : Theme.text

    function alpha(source, amount) {
        return Qt.rgba(source.r, source.g, source.b, amount);
    }

    implicitHeight: 28
    implicitWidth: Math.max(64, contentRow.implicitWidth + leftPadding + rightPadding)
    padding: 0
    leftPadding: 12
    rightPadding: 12
    hoverEnabled: true
    focusPolicy: Qt.NoFocus
    font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 1; bold: true }

    contentItem: Row {
        id: contentRow
        spacing: 6

        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: control.iconText !== ""
            text: control.iconText
            color: control.enabled ? control.tint : Theme.muted
            opacity: control.enabled ? 1 : 0.5
            font { family: Theme.iconFontFamily; pixelSize: control.iconSize }
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: control.text !== ""
            text: control.text
            color: control.enabled ? control.tint : Theme.muted
            opacity: control.enabled ? 1 : 0.5
            elide: Text.ElideRight
            font: control.font

            Behavior on color { ColorAnimation { duration: 120 } }
        }
    }

    background: Rectangle {
        radius: height / 2
        color: {
            if (!control.enabled)
                return control.variant === "ghost" ? "transparent" : control.alpha(Theme.surfaceBase, 0.25);
            if (control.variant === "normal")
                return control.down ? Theme.surfaceHover
                    : control.hovered ? Theme.surfaceHover : Theme.surface;
            if (control.variant === "ghost")
                return control.down || control.hovered ? Theme.surfaceHover : "transparent";
            return control.alpha(control.tint, control.down ? 0.34 : control.hovered ? 0.24 : 0.14);
        }
        border.width: 1
        border.color: {
            if (!control.enabled)
                return control.alpha(Theme.border, 0.4);
            if (control.variant === "normal")
                return control.hovered ? Theme.border : control.alpha(Theme.border, 0.6);
            if (control.variant === "ghost")
                return "transparent";
            return control.alpha(control.tint, control.hovered ? 0.8 : 0.5);
        }

        Behavior on color { ColorAnimation { duration: 120 } }
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
    }
}
