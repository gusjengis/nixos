"""Pin SF Pro's text optical master, retaining real weight and italic variants.

Use a private family so browser UI changes cannot replace SF Pro on web pages
or change other applications. CoreText selects opsz=17 at UI sizes 12–17pt;
the public variable font otherwise defaults to the display master (opsz=28).
"""
from pathlib import Path
import sys

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont


def prepare(source, destination, italic=False):
    font = TTFont(source, recalcTimestamp=False)
    # Keep only the standard weight axis. Italic also has a private YAXS axis;
    # leave its grade at the default rather than exposing a second weight axis.
    limits = {axis.axisTag: axis.defaultValue for axis in font["fvar"].axes
              if axis.axisTag != "wght"}
    limits["opsz"] = 17
    instantiateVariableFont(font, limits, inplace=True)
    family = "Chromium UI SF Pro"
    style = "Italic" if italic else "Regular"
    postscript = "ChromiumUISFPro-" + style
    names = font["name"]
    for record in list(names.names):
        value = {
            1: family, 2: style, 3: postscript, 4: family + " " + style,
            6: postscript, 16: family, 17: style, 21: family, 22: style,
        }.get(record.nameID)
        if value is not None:
            names.setName(value, record.nameID, record.platformID,
                          record.platEncID, record.langID)
    # Original named-instance PostScript names identify the unmodified family.
    for instance in font["fvar"].instances:
        instance.postscriptNameID = 0xFFFF
    font.save(destination)


if __name__ == "__main__":
    source, destination = map(Path, sys.argv[1:])
    for name, italic in (("SF-Pro.ttf", False), ("SF-Pro-Italic.ttf", True)):
        prepare(source / name, destination / ("Chromium-UI-" + name), italic)
