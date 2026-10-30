import QtQuick

// Menu-bar Ethernet mark: opposing chevrons around three connection dots.
Canvas {
    id: root

    property color color: "white"

    implicitWidth: 22
    implicitHeight: 16
    onColorChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()

    onPaint: {
        const ctx = getContext("2d");
        ctx.reset();
        ctx.scale(width / 22, height / 16);
        ctx.strokeStyle = root.color;
        ctx.fillStyle = root.color;
        ctx.lineWidth = 2;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.beginPath();
        ctx.moveTo(5.5, 3);
        ctx.lineTo(1.5, 8);
        ctx.lineTo(5.5, 13);
        ctx.moveTo(16.5, 3);
        ctx.lineTo(20.5, 8);
        ctx.lineTo(16.5, 13);
        ctx.stroke();
        for (let x = 7.5; x <= 14.5; x += 3.5) {
            ctx.beginPath();
            ctx.arc(x, 8, 1.1, 0, Math.PI * 2);
            ctx.fill();
        }
    }
}
