import json
import os
from pathlib import Path
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zlib

import opencode_grid as panel


ROOT = Path(__file__).resolve().parent


def png_pixels(path):
    """Decode actual Qt grabToImage captures without an extra image dependency."""
    data = Path(path).read_bytes()
    w, h, depth, kind = struct.unpack(">IIBB", data[16:26])
    if depth != 8 or kind not in (2, 6):
        raise AssertionError(f"Unexpected screenshot format {depth=}, {kind=}")
    channels, offset, compressed = (4 if kind == 6 else 3), 8, b""
    while offset < len(data):
        size = struct.unpack(">I", data[offset:offset + 4])[0]
        if data[offset + 4:offset + 8] == b"IDAT":
            compressed += data[offset + 8:offset + 8 + size]
        offset += size + 12
    raw, stride, previous, rows = zlib.decompress(compressed), w * channels, bytearray(w * channels), []
    for y in range(h):
        mode = raw[y * (stride + 1)]
        row = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for x in range(stride):
            left = row[x - channels] if x >= channels else 0
            up, diagonal = previous[x], previous[x - channels] if x >= channels else 0
            if mode == 1:
                predictor = left
            elif mode == 2:
                predictor = up
            elif mode == 3:
                predictor = (left + up) // 2
            elif mode == 4:
                target = left + up - diagonal
                predictor = min((left, up, diagonal), key=lambda value: abs(target - value))
            elif mode == 0:
                predictor = 0
            else:
                raise AssertionError(f"Unknown PNG filter {mode}")
            row[x] = (row[x] + predictor) % 256
        rows.append(bytes(row))
        previous = row
    return channels, rows


def crop_pixels(image, x, y, width, height):
    channels, rows = image
    return b"".join(row[x * channels:(x + width) * channels] for row in rows[y:y + height])


def session(index=0, title="macOS-Style OpenCode Session Widget with Liquid Glass"):
    return dict(title=title, state="working", mode="build", color="#bc8cff", pane=f"%{index}",
                directory="/tmp/Context", tmux_name="context-id", icon="⠋")


class GridTest(unittest.TestCase):
    def test_every_line_is_exactly_the_requested_number_of_cells(self):
        grid = panel.compose([session()], {}, 70, 8, 0)
        self.assertEqual(len(grid.cells), 8)
        for row in grid.cells:
            self.assertEqual(len(row), 70)
            self.assertEqual(sum(panel.width(c) for cell in row for c in cell.text), 70)
        self.assertEqual("".join(cell.text for cell in grid.cells[1]).strip("│ "), "opencode")

    def test_titles_contexts_and_icons_occupy_explicit_terminal_rows(self):
        grid = panel.compose([session(0), session(1)], {}, 70, 12, 1)
        for top in (3, 7):
            self.assertEqual(grid.cells[top][2].text, "⠙")
            self.assertTrue(grid.cells[top][4].bold)
            self.assertEqual(grid.cells[top + 2][4].color, panel.MUTED)
            self.assertFalse(grid.cells[top + 2][4].bold)
            self.assertTrue(all(cell.text == " " for cell in grid.cells[top + 3][1:-1]))

    def test_long_and_wide_titles_wrap_without_overwriting_border_or_context(self):
        grid = panel.compose([session(title="界e\u0301" * 100)], {}, 70, 8, 0)
        for row in (3, 4, 5):
            self.assertEqual(grid.cells[row][-1].text, "│")
            self.assertEqual(sum(panel.width(c) for cell in grid.cells[row] for c in cell.text), 70)
        self.assertIn("…", "".join(cell.text for cell in grid.cells[4]))
        self.assertEqual(grid.cells[5][4].text, "C")

    def test_control_characters_cannot_modify_terminal_output(self):
        grid = panel.compose([session(title="bad\x1b[2J\nname")], {}, 70, 8, 0)
        self.assertNotIn("\x1b", "".join(cell.text for row in grid.cells for cell in row))

    def test_scroll_slice_and_hit_geometry_share_same_cell_grid(self):
        sessions = [session(i, f"Session {i}") for i in range(10)]
        grid = panel.compose(sessions, {}, 70, 12, 0, offset=3, selected=4)
        self.assertIn("Session 3", "".join(cell.text for cell in grid.cells[3]))
        self.assertIn("Session 4", "".join(cell.text for cell in grid.cells[7]))
        self.assertEqual(grid.cells[2][-3].text, "↑")
        self.assertEqual(grid.cells[-1][-3].text, "↓")
        self.assertEqual(grid.cells[7][4].background, panel.SELECTION)
        self.assertEqual(grid.cells[6][4].background, panel.BACKGROUND)

    def test_native_decoration_does_not_leave_square_character_box(self):
        grid = panel.compose([session()], {}, 70, 8, 0, character_border=False)
        self.assertTrue(all(cell.text == " " for cell in grid.cells[0] + grid.cells[-1]))
        self.assertTrue(all(row[0].text == row[-1].text == " " for row in grid.cells))
        scrolling = panel.compose([session(i) for i in range(10)], {}, 70, 12, 0, character_border=False)
        self.assertEqual(scrolling.cells[-1][-3].text, "↓")


@unittest.skipUnless(shutil.which("kitty"), "Kitty native rasterizer not installed")
class RendererTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = str(ROOT / "opencode-renderer.py")
        cls.process = subprocess.Popen(["kitty", "+runpy", f"import runpy; runpy.run_path({path!r}, run_name='__main__')"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        cls.ready = cls.read()

    @classmethod
    def read(cls):
        if not select.select([cls.process.stdout], [], [], 5)[0]:
            raise AssertionError("Kitty renderer timed out")
        return json.loads(cls.process.stdout.readline())

    @classmethod
    def render(cls, **options):
        request = dict(sessions=[session(0), session(1)], rows=12, frame=0)
        request.update(options)
        cls.process.stdin.write(json.dumps(request) + "\n")
        cls.process.stdin.flush()
        return cls.read()

    @classmethod
    def tearDownClass(cls):
        cls.process.stdin.close()
        cls.process.wait(timeout=3)
        cls.process.stdout.close()

    def test_reuses_one_process_and_two_frame_files(self):
        frames = [self.render(frame=index) for index in range(3)]
        self.assertIsNone(self.process.poll())
        self.assertEqual(frames[2]["generation"] - frames[0]["generation"], 2)
        self.assertEqual(frames[0]["path"], frames[2]["path"])
        self.assertNotEqual(frames[0]["path"], frames[1]["path"])
        self.assertLess(frames[-1]["renderMs"], 80, "Warm rendering must keep up with spinner cadence")

    def test_kitty_cell_masks_and_linear_composition_preserve_crisp_spinner(self):
        frame = self.render()
        data = Path(frame["path"]).read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        w, h = struct.unpack(">II", data[16:24])
        self.assertEqual((w, h), (70 * self.ready["cellWidth"], 12 * self.ready["cellHeight"]))
        offset, compressed = 8, b""
        while offset < len(data):
            size = struct.unpack(">I", data[offset:offset + 4])[0]
            if data[offset + 4:offset + 8] == b"IDAT":
                compressed += data[offset + 8:offset + 8 + size]
            offset += size + 12
        raw = zlib.decompress(compressed)
        cw, ch = self.ready["cellWidth"], self.ready["cellHeight"]
        colors = []
        for y in range(3 * ch, 4 * ch):
            row = raw[y * (w * 3 + 1) + 1:(y + 1) * (w * 3 + 1)]
            for x in range(2 * cw, 3 * cw):
                colors.append(tuple(row[x * 3:x * 3 + 3]))
        self.assertEqual(set(colors), {(13, 17, 23), (188, 140, 255)})
        if (cw, ch) == (8, 15):
            self.assertEqual(colors.count((188, 140, 255)), 6, "Three Braille dots must each be exactly 2x1")

    @unittest.skipUnless(shutil.which("quickshell") and os.environ.get("WAYLAND_DISPLAY"), "Requires live Quickshell/Wayland")
    def test_qml_cached_popup_geometry_latency_and_navigation(self):
        frame = self.render()
        result = subprocess.run(["quickshell", "--path", str(ROOT / "test_opencode_popup.qml")],
            env={**os.environ, "TEST_BITMAP_PATH": frame["path"], "TEST_BITMAP_WIDTH": str(frame["width"]),
                 "TEST_BITMAP_HEIGHT": str(frame["height"]), "TEST_CELL_HEIGHT": str(self.ready["cellHeight"])},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=8)
        self.assertNotIn("FAILED:", result.stdout)
        self.assertIn("PASS: cached first paint", result.stdout)

    @unittest.skipUnless(shutil.which("quickshell") and os.environ.get("WAYLAND_DISPLAY"), "Requires live Quickshell/Wayland")
    def test_visible_pixels_update_when_double_buffer_filename_is_reused(self):
        frame = self.render(frame=0)
        with tempfile.TemporaryDirectory() as directory:
            gui = subprocess.Popen(["quickshell", "--path", str(ROOT / "test_opencode_popup.qml")],
                env={**os.environ, "TEST_BITMAP_PATH": frame["path"], "TEST_BITMAP_WIDTH": str(frame["width"]),
                     "TEST_BITMAP_HEIGHT": str(frame["height"]), "TEST_CELL_HEIGHT": str(self.ready["cellHeight"]),
                     "TEST_BITMAP_GENERATION": str(frame["generation"]), "TEST_CAPTURE_DIR": directory},
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            output = bytearray()

            def wait_for(marker):
                deadline = time.monotonic() + 6
                while marker not in output and time.monotonic() < deadline:
                    if select.select([gui.stdout], [], [], .1)[0]:
                        data = os.read(gui.stdout.fileno(), 65536)
                        if not data:
                            break
                        output.extend(data)
                self.assertIn(marker, output, output.decode(errors="replace"))

            def advance(**options):
                self.render(**options)
                updated = self.render(**options)
                self.assertEqual(updated["path"], frame["path"], "Regression must overwrite exact same filename")
                subprocess.run(["quickshell", "ipc", "--pid", str(gui.pid), "call", "frameTest", "advance",
                                str(updated["generation"])], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            try:
                wait_for(b"FRAME_CAPTURED:0")
                advance(frame=2)
                wait_for(b"FRAME_CAPTURED:1")
                changed = session(0, "Changed live title")
                changed.update(state="input", icon="?", color="#d29922")
                advance(sessions=[changed, session(1)])
                wait_for(b"FRAME_CAPTURED:2")
                gui.wait(timeout=3)
                self.assertNotIn(b"FAILED:", output)
                images = [png_pixels(Path(directory) / f"frame-{index}.png") for index in range(3)]
                cw, ch = self.ready["cellWidth"], self.ready["cellHeight"]
                spinner = (2 + 2 * cw, 2 + 12 + 3 * ch, cw, ch)
                title = (2 + 4 * cw, 2 + 12 + 3 * ch, 40 * cw, ch)
                self.assertNotEqual(crop_pixels(images[0], *spinner), crop_pixels(images[1], *spinner),
                                    "Displayed spinner must advance, not just renderer counter")
                self.assertEqual(crop_pixels(images[0], *title), crop_pixels(images[1], *title),
                                 "Spinner-only frame must preserve title pixels")
                self.assertNotEqual(crop_pixels(images[1], *title), crop_pixels(images[2], *title),
                                    "Changed session title must reach displayed pixels")
                self.assertNotEqual(crop_pixels(images[1], *spinner), crop_pixels(images[2], *spinner),
                                    "Question status must replace spinner in displayed pixels")
            finally:
                if gui.poll() is None:
                    gui.terminate()
                    gui.wait(timeout=3)
                gui.stdout.close()


if __name__ == "__main__":
    unittest.main()
