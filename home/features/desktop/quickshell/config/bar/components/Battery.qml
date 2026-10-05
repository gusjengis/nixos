import QtQuick
import QtQuick.Effects
import "../../theme"
import "../../widgets"

// macOS battery menu extra: the SF "battery.0" outline with a level fill
// inset inside it, and a bolt knocked out of both while charging.
Rectangle {
    id: root

    property var batteryService: null
    readonly property bool popupVisible: popup.visible
    readonly property real level: batteryService ? Math.max(0, Math.min(100, batteryService.percentage)) / 100 : 0
    readonly property bool charging: !!batteryService && batteryService.charging

    visible: !!batteryService && batteryService.available
    implicitWidth: 36
    implicitHeight: Theme.barItemHeight
    radius: height / 2
    color: popup.visible ? Theme.barHoverFill : "transparent"

    Item {
        id: icon

        readonly property rect bounds: metrics.tightBoundingRect
        // Interior of the outline as fractions of the glyph's tight bounds,
        // measured from the font; the nub sits right of bodyRight.
        readonly property real innerLeft: 0.0553
        readonly property real innerRight: 0.8377
        readonly property real innerTop: 0.1203
        readonly property real innerBottom: 0.8797
        readonly property real bodyCenterX: 0.4456
        readonly property real gap: 1

        anchors.centerIn: parent
        width: bounds.width
        height: bounds.height

        TextMetrics {
            id: metrics
            font: outline.font
            text: outline.text
        }

        TextMetrics {
            id: boltMetrics
            font: bolt.font
            text: bolt.text
        }

        Item {
            anchors.fill: parent
            layer.enabled: true
            layer.effect: MultiEffect {
                maskEnabled: root.charging
                maskInverted: true
                maskSource: boltMask
                maskThresholdMin: 0.3
                maskSpreadAtMin: 0.2
            }

            SFSymbol {
                id: outline
                x: -icon.bounds.x
                y: -(baselineOffset + icon.bounds.y)
                symbol: "battery.0"
                size: 17
                color: Theme.barText
            }

            Rectangle {
                readonly property real maxWidth: icon.width * (icon.innerRight - icon.innerLeft) - icon.gap * 2
                x: icon.width * icon.innerLeft + icon.gap
                y: icon.height * icon.innerTop + icon.gap
                width: Math.max(1.5, maxWidth * root.level)
                height: icon.height * (icon.innerBottom - icon.innerTop) - icon.gap * 2
                radius: 1.5
                color: Theme.barText
            }
        }

        // Heavier copy of the bolt, used only as the knockout mask so the
        // visible bolt gets a thin transparent gap around it.
        Item {
            id: boltMask
            anchors.fill: parent
            layer.enabled: true
            visible: false

            TextMetrics {
                id: maskMetrics
                font: boltKnockout.font
                text: boltKnockout.text
            }

            SFSymbol {
                id: boltKnockout
                x: icon.width * icon.bodyCenterX - maskMetrics.tightBoundingRect.width / 2 - maskMetrics.tightBoundingRect.x
                y: icon.height / 2 - maskMetrics.tightBoundingRect.height / 2 - maskMetrics.tightBoundingRect.y - baselineOffset
                symbol: "bolt.fill"
                size: bolt.size + 2
                font.weight: Font.Black
                color: "white"
            }
        }

        SFSymbol {
            id: bolt
            visible: root.charging
            x: icon.width * icon.bodyCenterX - boltMetrics.tightBoundingRect.width / 2 - boltMetrics.tightBoundingRect.x
            y: icon.height / 2 - boltMetrics.tightBoundingRect.height / 2 - boltMetrics.tightBoundingRect.y - baselineOffset
            symbol: "bolt.fill"
            size: 13
            color: Theme.barText
        }
    }

    MouseArea {
        anchors.fill: parent
        onClicked: popup.toggle(root)
    }

    BatteryPopup {
        id: popup
        batteryService: root.batteryService
    }
}
