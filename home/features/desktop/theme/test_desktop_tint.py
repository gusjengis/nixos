"""Behavioral fixtures obtained by executing SkyLight, not by fitting pixels."""
import unittest
from unittest.mock import patch
import json
import os

import numpy as np

from desktop_tint import Payload, average_color, material, FILL, convert_gamut, gamut_matrices, hyprland, active_wallpapers


class NativeAverageOracle(unittest.TestCase):
    def setUp(self):
        y, x = np.mgrid[:8, :8].astype(np.float32)
        pixels = np.stack((x / 7, y / 7, (x + y) / 14, np.ones_like(x)), axis=-1)
        self.payload = Payload(pixels, (0, 0, 8, 8), scale=1)

    def test_native_regions_including_left_index_and_fractional_area(self):
        # macOS 27.0.1 / 26A434; Payload::average_color invoked with the same
        # synthetic 8x8 inclusive integral image. Float32 results captured via
        # LLDB; the alpha values distinguish this from a conventional mean.
        cases = [
            ((0, 0, 8, 8), [0.5079365372657776] * 3 + [1]),
            ((0, 0, 4, 4), [0.2063492238521576] * 3 + [1]),
            ((1, 1, 4, 4), [0.3174603283405304, 0.2698412835597992, 0.2857142984867096, 0.7619048357009888]),
            ((4, 0, 4, 8), [0.6507936716079712, 0.3809524178504944, 0.5079365372657776, 0.7619048357009888]),
            ((0.25, 0.25, 3.5, 3.5), [0.0952381044626236] * 3 + [0.7460317611694336]),
            ((-1, -1, 5, 5), [0.2063492238521576] * 3 + [1]),
        ]
        for rect, expected in cases:
            with self.subTest(rect=rect):
                np.testing.assert_allclose(self.payload.average(rect), expected, atol=6e-8, rtol=0)

    def test_cross_display_weighting_and_outside_desktop(self):
        red = Payload(np.full((8, 8, 4), [1, 0, 0, 1], dtype=np.float32), (0, 0, 8, 8), 1)
        blue = Payload(np.full((8, 8, 4), [0, 0, 1, 1], dtype=np.float32), (8, 0, 8, 8), 1)
        np.testing.assert_allclose(average_color([red, blue], (0, 0, 16, 8)), [.5, 0, .5, 1])
        np.testing.assert_array_equal(average_color([red, blue], (-20, 0, 4, 4)), [0, 0, 0, 0])

    def test_native_material_in_reference_working_gamut(self):
        # Native contentBackground beside a flat reconstructed CALayer in the
        # same screenshot. Values are the screenshot's encoded Display P3.
        cases = [([0, 0, 0, 1], [27, 27, 27]), ([.5, .5, .5, 1], [40, 40, 40]),
                 ([1, 1, 1, 1], [53, 53, 53]), ([1, 0, 0, 1], [51, 32, 31]),
                 ([0, 1, 0, 1], [39, 53, 35]), ([0, 0, 1, 1], [27, 27, 52])]
        for tone, expected in cases:
            with self.subTest(tone=tone):
                p3 = convert_gamut(material(tone), gamut_matrices()[0])
                actual = np.floor(np.asarray(p3) * 255 + .5)
                np.testing.assert_allclose(actual, expected, atol=1, rtol=0)

    def test_absent_and_partial_samples_preserve_alpha(self):
        self.assertEqual(material([0, 0, 0, 0]), [FILL] * 3)
        # White is neutral in either working gamut. A partial premultiplied
        # sample must be weaker than an opaque white sample, not equally bright.
        partial = material([.5, .5, .5, .5])
        self.assertTrue(all(FILL < c < material([1, 1, 1, 1])[0] for c in partial))


class ServiceCompositorIdentity(unittest.TestCase):
    def test_live_wallpaper_ipc_including_spaces_and_colons(self):
        with patch("subprocess.check_output", return_value="HDMI-A-1: /wallpapers/new: blue sky.jpg\nDP-1: /wallpapers/red.png\n"):
            self.assertEqual(active_wallpapers(), {
                "HDMI-A-1": "/wallpapers/new: blue sky.jpg", "DP-1": "/wallpapers/red.png"})
        with patch("subprocess.check_output", side_effect=FileNotFoundError):
            self.assertEqual(active_wallpapers(), {})
        with patch("subprocess.check_output", return_value="error: hyprpaper is not running\n"):
            self.assertEqual(active_wallpapers(), {})

    def test_service_without_shell_environment_resolves_unique_instance(self):
        instances = [{"instance": "desktop", "wl_socket": "wayland-1"}]
        with patch.dict(os.environ, {}, clear=True), patch("subprocess.check_output", side_effect=[json.dumps(instances), "[]"]) as command:
            self.assertEqual(hyprland("monitors"), [])
            self.assertEqual(os.environ["HYPRLAND_INSTANCE_SIGNATURE"], "desktop")
            self.assertEqual(command.call_args_list[0].args[0], ["hyprctl", "instances", "-j"])

    def test_nested_compositor_requires_display_identity(self):
        instances = [{"instance": "desktop", "wl_socket": "wayland-1"}, {"instance": "nested", "wl_socket": "wayland-2"}]
        with patch.dict(os.environ, {}, clear=True), patch("subprocess.check_output", return_value=json.dumps(instances)):
            with self.assertRaisesRegex(ValueError, "cannot identify"):
                hyprland("monitors")
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-1"}, clear=True), patch("subprocess.check_output", side_effect=[json.dumps(instances), "[]"]):
            hyprland("monitors")
            self.assertEqual(os.environ["HYPRLAND_INSTANCE_SIGNATURE"], "desktop")


if __name__ == "__main__":
    unittest.main()
