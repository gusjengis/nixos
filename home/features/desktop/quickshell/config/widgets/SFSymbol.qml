import QtQuick

// An SF Symbol, drawn from the Supplementary Private Use Area glyphs that
// ship inside SF Pro. Codepoints were read off the font itself (SF Symbols
// has no public name table on Linux), so add new names here after checking
// the glyph renders as expected.
Text {
    id: root

    property string symbol: ""
    property real size: 16

    readonly property var codepoints: ({
        "xmark": 0x100184,
        "checkmark": 0x100185,
        "chevron.left": 0x100189,
        "chevron.right": 0x10018A,
        "globe": 0x1001AA,
        "sun.min.fill": 0x1001AC,
        "sun.max.fill": 0x1001AE,
        "moon.fill": 0x1001BA,
        "folder.fill": 0x100216,
        "play.fill": 0x100284,
        "pause.fill": 0x100286,
        "backward.fill": 0x10028A,
        "forward.fill": 0x10028C,
        "speaker.fill": 0x1002A1,
        "speaker.slash.fill": 0x1002A3,
        "speaker.wave.1.fill": 0x1002A5,
        "speaker.wave.2.fill": 0x1002A7,
        "speaker.wave.3.fill": 0x1002A9,
        "magnifyingglass": 0x1002AB,
        "mic.fill": 0x1002B1,
        "mic.slash.fill": 0x1002B3,
        "bolt.fill": 0x1002E6,
        "display": 0x1003B2,
        "headphones": 0x100448,
        "wifi": 0x100647,
        "wifi.slash": 0x100648,
        "battery.100": 0x1006E8,
        "battery.25": 0x1006E9,
        "battery.0": 0x1006EA,
        "switch.2": 0x10070A
    })

    text: codepoints[symbol] !== undefined ? String.fromCodePoint(codepoints[symbol]) : ""
    font {
        family: "SF Pro"
        pixelSize: root.size
        weight: Font.Medium
    }
}
