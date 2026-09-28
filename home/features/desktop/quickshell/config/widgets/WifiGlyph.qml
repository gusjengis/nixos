import QtQuick
import QtQuick.Effects

// macOS menu bar Wi-Fi: the SF "wifi" symbol drawn dim, with the lit part
// revealed by a circle centred on the glyph's apex. The symbol's wedge and
// arcs are concentric about that apex, so the radius picks how many of them
// light up (0-3); the thresholds sit in the gaps between the parts.
Item {
    id: root

    property bool powered: true
    property int level: 3
    property color color: "white"
    property real size: 16

    readonly property rect bounds: metrics.tightBoundingRect
    // Apex-relative distances as a fraction of glyph height, measured from
    // the font: wedge ends ~0.29, middle arc spans 0.46-0.64, outer 0.82-1.
    readonly property real litRadius: level >= 3 ? height * 2 : level === 2 ? height * 0.73 : level === 1 ? height * 0.375 : 0

    implicitWidth: bounds.width
    implicitHeight: bounds.height

    TextMetrics {
        id: metrics
        font: dim.font
        text: dim.text
    }

    SFSymbol {
        id: dim
        x: -root.bounds.x
        y: -(baselineOffset + root.bounds.y)
        symbol: root.powered ? "wifi" : "wifi.slash"
        size: root.size
        color: root.color
        opacity: root.powered && root.level < 3 ? 0.3 : 1
    }

    Item {
        anchors.fill: parent
        visible: root.powered && root.level > 0 && root.level < 3
        layer.enabled: visible
        layer.effect: MultiEffect {
            maskEnabled: true
            maskSource: mask
        }

        SFSymbol {
            x: dim.x
            y: dim.y
            symbol: "wifi"
            size: root.size
            color: root.color
        }
    }

    Item {
        id: mask
        anchors.fill: parent
        layer.enabled: true
        visible: false

        Rectangle {
            width: root.litRadius * 2
            height: width
            radius: width / 2
            x: parent.width / 2 - root.litRadius
            y: parent.height - root.litRadius
        }
    }
}
