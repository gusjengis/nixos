import QtQuick
import QtQuick.Controls
import "../theme"

Button {
    id: control
    property bool primary: false
    property bool destructive: false
    implicitHeight: 34
    implicitWidth: contentItem.implicitWidth + 24
    font { family: Theme.fontFamily; pixelSize: 13; weight: Font.Medium }
    opacity: enabled ? 1 : 0.35
    contentItem: Text {
        text: control.text
        font: control.font
        color: "#f0f1f5"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: 7
        color: control.destructive ? (control.down ? "#943f44" : "#b54c53") : control.primary ? (control.down ? "#245da8" : "#3478cf")
            : control.down ? "#454a57" : control.hovered ? "#3c414e" : "#343944"
        border.color: control.activeFocus ? "#8bb7f1" : "#535967"
        border.width: control.activeFocus ? 2 : 1
    }
}
