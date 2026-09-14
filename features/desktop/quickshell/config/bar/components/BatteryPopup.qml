import QtQuick
import Quickshell
import Quickshell.Services.UPower
import "../../theme"

PopupWindow {
    id: popup

    property var batteryService: null

    function toggle(anchorItem) {
        if (visible) {
            visible = false;
            return;
        }
        anchor.item = anchorItem;
        visible = true;
        chart.requestPaint();
    }

    function duration(seconds) {
        if (!seconds || seconds <= 0)
            return "Calculating estimate";
        const totalMinutes = Math.round(seconds / 60);
        const hours = Math.floor(totalMinutes / 60);
        const minutes = totalMinutes % 60;
        if (hours === 0)
            return minutes + " min";
        if (minutes === 0)
            return hours + " hr";
        return hours + " hr " + minutes + " min";
    }

    function statusText() {
        if (!batteryService)
            return "";
        if (batteryService.device.state === UPowerDeviceState.FullyCharged)
            return "Fully charged";
        if (batteryService.charging)
            return duration(batteryService.estimateSeconds) + " until full";
        return duration(batteryService.estimateSeconds) + " remaining";
    }

    anchor.rect.x: (anchor.item ? anchor.item.width : 0) - width
    anchor.rect.y: Theme.barPopupY(anchor.item)
    implicitWidth: 370
    implicitHeight: 230
    color: "transparent"
    grabFocus: true

    Rectangle {
        anchors.fill: parent
        radius: Theme.windowRadius
        color: Theme.background
        border { width: Theme.windowBorderWidth; color: Theme.windowBorder }
    }

    Column {
        anchors { fill: parent; margins: 14 }
        spacing: 10

        Row {
            width: parent.width
            spacing: 8

            Text {
                text: popup.batteryService && popup.batteryService.charging ? "Charging" : "Battery"
                color: Theme.text
                font { family: Theme.fontFamily; pixelSize: 16; bold: true }
            }

            Text {
                text: (popup.batteryService ? popup.batteryService.percentage : 0) + "%"
                color: popup.batteryService && popup.batteryService.percentage <= 15
                    ? Theme.danger : Theme.accent
                font { family: Theme.fontFamily; pixelSize: 16; bold: true }
            }
        }

        Text {
            text: popup.statusText()
            color: Theme.muted
            font { family: Theme.fontFamily; pixelSize: Theme.fontSize }
        }

        Rectangle {
            width: parent.width
            height: 140
            radius: Theme.radius
            color: Theme.surface
            border { width: 1; color: Theme.border }

            Canvas {
                id: chart
                anchors { fill: parent; leftMargin: 10; rightMargin: 10; topMargin: 10; bottomMargin: 22 }

                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()
                onPaint: {
                    const ctx = getContext("2d");
                    ctx.clearRect(0, 0, width, height);

                    ctx.strokeStyle = Theme.border;
                    ctx.lineWidth = 1;
                    for (let i = 0; i <= 4; i++) {
                        const y = i * height / 4;
                        ctx.beginPath();
                        ctx.moveTo(0, y);
                        ctx.lineTo(width, y);
                        ctx.stroke();
                    }

                    const samples = popup.batteryService ? popup.batteryService.history : [];
                    if (!samples || samples.length === 0)
                        return;

                    const end = Date.now();
                    const start = end - 3 * 60 * 60 * 1000;
                    function pointX(sample) {
                        return Math.max(0, (sample.timestamp - start) / (end - start) * width);
                    }
                    function pointY(sample) {
                        return height - sample.percentage / 100 * height;
                    }

                    ctx.beginPath();
                    ctx.moveTo(pointX(samples[0]), height);
                    for (let j = 0; j < samples.length; j++)
                        ctx.lineTo(pointX(samples[j]), pointY(samples[j]));
                    ctx.lineTo(width, height);
                    ctx.closePath();
                    ctx.fillStyle = Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18);
                    ctx.fill();

                    ctx.beginPath();
                    for (let k = 0; k < samples.length; k++) {
                        const x = pointX(samples[k]);
                        const y = pointY(samples[k]);
                        if (k === 0)
                            ctx.moveTo(x, y);
                        else
                            ctx.lineTo(x, y);
                    }
                    ctx.strokeStyle = Theme.accent;
                    ctx.lineWidth = 2;
                    ctx.stroke();

                    const last = samples[samples.length - 1];
                    ctx.beginPath();
                    ctx.arc(width - 2, pointY(last), 3, 0, Math.PI * 2);
                    ctx.fillStyle = Theme.accent;
                    ctx.fill();
                }

                Connections {
                    target: popup.batteryService || null
                    function onHistoryChanged() { chart.requestPaint(); }
                }
            }

            Text {
                anchors { left: parent.left; leftMargin: 10; bottom: parent.bottom; bottomMargin: 5 }
                text: "3 hours ago"
                color: Theme.muted
                font { family: Theme.fontFamily; pixelSize: 10 }
            }

            Text {
                anchors { right: parent.right; rightMargin: 10; bottom: parent.bottom; bottomMargin: 5 }
                text: "Now"
                color: Theme.muted
                font { family: Theme.fontFamily; pixelSize: 10; bold: true }
            }
        }
    }

    Shortcut {
        sequence: "Escape"
        enabled: popup.visible
        onActivated: popup.visible = false
    }
}
