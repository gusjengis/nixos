"""Verify built UI fonts against Apple's source at the captured Mac axes.

Usage: python test_ui_font.py SOURCE_FONT_DIRECTORY BUILT_FONT_DIRECTORY
Requires fontTools. Compares outlines, advances, character coverage, weights,
and italic flags, catching loss of variants during partial instancing.
"""
from pathlib import Path
import sys

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont


source, output = map(Path, sys.argv[1:])
for name in ("SF-Pro.ttf", "SF-Pro-Italic.ttf"):
    original = TTFont(source / name)
    actual = TTFont(output / ("Chromium-UI-" + name))
    assert [a.axisTag for a in actual["fvar"].axes] == ["wght"]
    assert actual["name"].getDebugName(1) == "Chromium UI SF Pro"
    assert actual["OS/2"].usWeightClass == 400
    assert original["OS/2"].fsSelection == actual["OS/2"].fsSelection
    assert original.getBestCmap() == actual.getBestCmap()
    largest_error = 0
    for weight in (400, 500, 600, 700):
        expected_glyphs = original.getGlyphSet(
            location={"opsz": 17, "wdth": 100, "wght": weight})
        actual_glyphs = actual.getGlyphSet(location={"wght": weight})
        for character in "TestingYouTubeSettingsGoogleChrome0123456789":
            glyph = actual.getBestCmap()[ord(character)]
            expected = DecomposingRecordingPen(expected_glyphs)
            result = DecomposingRecordingPen(actual_glyphs)
            expected_glyphs[glyph].draw(expected)
            actual_glyphs[glyph].draw(result)
            assert len(expected.value) == len(result.value)
            for (op1, points1), (op2, points2) in zip(expected.value, result.value):
                assert op1 == op2
                for p1, p2 in zip(points1, points2):
                    if p1 is None or p2 is None:  # TrueType implied closing point.
                        assert p1 is p2
                        continue
                    largest_error = max(largest_error,
                                        *(abs(x-y) for x, y in zip(p1, p2)))
            assert abs(expected_glyphs[glyph].width - actual_glyphs[glyph].width) <= 1
    assert largest_error <= 1, largest_error
    print(f"PASS {name}: weights 400/500/600/700 match text-master outlines; "
          f"max rounding {largest_error:.3f}/2048 em")
