import QtQuick

Canvas {
    id: root

    property real signal: 0
    property bool connected: true
    property color iconColor: "white"

    implicitWidth: 18
    implicitHeight: 18

    onSignalChanged: requestPaint()
    onEnabledChanged: requestPaint()
    onConnectedChanged: requestPaint()
    onIconColorChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()

    onPaint: {
        const context = getContext("2d");
        const scale = Math.min(width, height) / 17;
        const centerX = width / 2;
        const centerY = height * 0.85;
        const activeArcs = signal >= 75 ? 3 : signal >= 50 ? 2 : signal >= 25 ? 1 : 0;
        const startAngle = Math.PI * 1.28;
        const endAngle = Math.PI * 1.72;

        function drawBand(innerRadius, outerRadius) {
            context.beginPath();
            context.arc(centerX, centerY, outerRadius * scale, startAngle, endAngle);
            context.arc(centerX, centerY, innerRadius * scale, endAngle, startAngle, true);
            context.closePath();
            context.fill();
        }

        context.reset();
        context.strokeStyle = iconColor;
        context.fillStyle = iconColor;
        context.lineCap = "round";

        context.globalAlpha = enabled && connected ? 1 : 0.25;
        context.beginPath();
        context.moveTo(centerX, centerY);
        context.arc(centerX, centerY, 3.15 * scale, startAngle, endAngle);
        context.closePath();
        context.fill();

        for (let level = 1; level <= 3; level++) {
            context.globalAlpha = enabled && connected && level <= activeArcs ? 1 : 0.2;
            const innerRadius = 4.025 + (level - 1) * 3.15;
            drawBand(innerRadius, innerRadius + 1.8);
        }

        if (!enabled) {
            context.globalAlpha = 1;
            context.lineWidth = 2 * scale;
            context.beginPath();
            context.moveTo(width * 0.22, height * 0.2);
            context.lineTo(width * 0.8, height * 0.82);
            context.stroke();
        }
    }
}
