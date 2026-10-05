import QtQuick
import Quickshell
import Quickshell.Services.UPower
import "../../theme"

GuardedPopupWindow {
    id: popup

    property var batteryService: null

    function toggle(anchorItem) {
        if (visible) {
            visible = false;
            return;
        }
        popup.anchorItem = anchorItem;
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

    popupX: (anchorItem ? anchorItem.width : 0) - popupWidth
    popupWidth: 310
    popupHeight: content.implicitHeight + 2 * Theme.menuPadding

    // macOS battery menu: bold title with the level on the right, secondary
    // status lines, then the recent-charge chart in place of Energy Mode.
    Column {
        id: content
        anchors { left: parent.left; right: parent.right; top: parent.top
            margins: Theme.menuPadding; leftMargin: Theme.menuTextInset; rightMargin: Theme.menuTextInset }
        spacing: 0

        Item {
            width: parent.width
            height: 34

            Text {
                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                text: "Battery"
                color: Theme.menuText
                font { family: Theme.fontFamily; pixelSize: Theme.menuFontSize; weight: Font.Bold }
            }

            Text {
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                text: (popup.batteryService ? popup.batteryService.percentage : 0) + "%"
                color: popup.batteryService && popup.batteryService.percentage <= 15
                    ? Theme.danger : Theme.menuSecondaryText
                font { family: Theme.fontFamily; pixelSize: Theme.menuFontSize; weight: Font.Medium }
            }
        }

        Text {
            width: parent.width
            height: 20
            verticalAlignment: Text.AlignVCenter
            text: "Power Source: " + (popup.batteryService && popup.batteryService.charging ? "Power Adapter" : "Battery")
            color: Theme.menuSecondaryText
            font { family: Theme.fontFamily; pixelSize: Theme.menuFontSize }
        }

        Text {
            width: parent.width
            height: 20
            verticalAlignment: Text.AlignVCenter
            text: popup.statusText()
            color: Theme.menuSecondaryText
            font { family: Theme.fontFamily; pixelSize: Theme.menuFontSize }
        }

        Item {
            width: parent.width
            height: Theme.menuSeparatorHeight
            Rectangle { anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 1; color: Theme.menuSeparator }
        }

        Text {
            width: parent.width
            height: 22
            verticalAlignment: Text.AlignVCenter
            text: "Last 3 Hours"
            color: Theme.menuSecondaryText
            font { family: Theme.fontFamily; pixelSize: Theme.menuFontSize - 1; weight: Font.DemiBold }
        }

        Item {
            width: parent.width
            height: 118

            Canvas {
                id: chart
                anchors { fill: parent; topMargin: 4; bottomMargin: 22 }

                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()
                onPaint: {
                    const ctx = getContext("2d");
                    ctx.clearRect(0, 0, width, height);

                    ctx.strokeStyle = Theme.menuSeparator;
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
                    ctx.fillStyle = Qt.rgba(0.204, 0.78, 0.349, 0.22);
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
                    ctx.strokeStyle = "#34c759";
                    ctx.lineWidth = 2;
                    ctx.stroke();

                    const last = samples[samples.length - 1];
                    ctx.beginPath();
                    ctx.arc(width - 2, pointY(last), 3, 0, Math.PI * 2);
                    ctx.fillStyle = "#34c759";
                    ctx.fill();
                }

                Connections {
                    target: popup.batteryService || null
                    function onHistoryChanged() { chart.requestPaint(); }
                }
            }

            Text {
                anchors { left: parent.left; bottom: parent.bottom; bottomMargin: 5 }
                text: "3 hours ago"
                color: Theme.menuSecondaryText
                font { family: Theme.fontFamily; pixelSize: 10 }
            }

            Text {
                anchors { right: parent.right; bottom: parent.bottom; bottomMargin: 5 }
                text: "Now"
                color: Theme.menuSecondaryText
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
