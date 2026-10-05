"""Regression model for RGBA8 placeholder coverage; no desktop connection."""
import math
import unittest

MARKER = 124 / 255


def old_match(rgb, alpha):
    return abs(rgb / alpha - MARKER) <= 1 / 255


def new_match(rgb, alpha):
    ink = rgb / alpha
    return ink <= 0.9 and abs(rgb - MARKER * alpha) <= 2 / 255


def pixel(background, alpha_byte, match):
    alpha = alpha_byte / 255
    rgb = math.floor(124 * alpha + 0.5) / 255
    if match(rgb, alpha):
        return min(255, background + 124 * alpha)
    return rgb * 255 + (1 - alpha) * background


class PlaceholderCoverage(unittest.TestCase):
    def test_old_bug_reproduced(self):
        rgb, alpha = 37 / 255, 77 / 255
        self.assertFalse(old_match(rgb, alpha))
        self.assertTrue(new_match(rgb, alpha))
        self.assertLess(pixel(128, 77, old_match), 128)
        self.assertGreater(pixel(128, 77, new_match), 165)

    def test_marker_sweep(self):
        for byte in range(2, 256):
            alpha = byte / 255
            rgb = math.floor(124 * alpha + 0.5) / 255
            self.assertTrue(new_match(rgb, alpha), byte)

    def test_white_caret_and_icons_unchanged(self):
        for byte in range(1, 256):
            alpha = byte / 255
            self.assertFalse(new_match(alpha, alpha), byte)

    def test_no_downward_coverage_steps(self):
        for background in (32, 80, 128, 147, 186):
            values = [pixel(background, byte, new_match) for byte in range(1, 256)]
            self.assertTrue(all(b >= a for a, b in zip(values, values[1:])), background)

    def test_additive_model_preserved(self):
        for background in (32, 80, 128, 147, 186):
            for byte in range(2, 256):
                self.assertAlmostEqual(pixel(background, byte, new_match),
                                       min(255, background + 124 * byte / 255))


if __name__ == "__main__":
    unittest.main()
