import QtQuick
import "theme"

// Ref4K label matches 14 pt system text, not the default 15 px display
// instance. Qt does not apply CoreText's system tracking automatically.
// opsz 17 selects the text outlines; spacing matches Mac holdout labels
// within 0.6 px. Pin the baseline independently of Qt font ascent.
Text {
    x: 13
    y: 18 - baselineOffset
    color: "#eaffffff"
    font {
        family: Theme.fontFamily
        pixelSize: 14
        weight: Font.Normal
        variableAxes: ({ "opsz": 17, "wght": 400 })
        letterSpacing: -0.25
        hintingPreference: Font.PreferNoHinting
    }
    renderType: Text.NativeRendering
}
