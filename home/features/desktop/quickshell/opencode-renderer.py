"""Persistent, headless Kitty rasterizer for the cell-grid popup.

Kitty supplies real glyph sprites, hinting, shaping and cell metrics. Its Linux
default shader blends those masks in linear light; do the same before emitting
an opaque sRGB bitmap. Qt only displays pixels and handles popup interaction.
"""
from functools import lru_cache
import json
import os
from pathlib import Path
import signal
import struct
import sys
import tempfile
import time
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
import opencode_grid as grid_model


def linear(value):
    value /= 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def srgb(value):
    value = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
    return max(0, min(255, round(value * 255)))


def rgb(color):
    return tuple(int(color[n:n + 2], 16) for n in (1, 3, 5))


@lru_cache(maxsize=128)
def palette(foreground, background):
    fg, bg = tuple(map(linear, rgb(foreground))), tuple(map(linear, rgb(background)))
    return tuple(bytes(srgb(f * (alpha / 255) + b * (1 - alpha / 255)) for f, b in zip(fg, bg))
                 for alpha in range(256))


def png(width, height, data):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
    stride = width * 3
    scanlines = b"".join(b"\0" + data[row * stride:(row + 1) * stride] for row in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"sRGB", b"\0") + chunk(b"IDAT", zlib.compress(scanlines, 1)) + chunk(b"IEND", b""))


class KittyRenderer:
    def __init__(self):
        from kitty.config import load_config
        from kitty.fonts.render import setup_for_testing
        config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "kitty/kitty.conf"
        self.options = load_config(str(config))
        self.context = setup_for_testing(str(self.options.font_family), float(self.options.font_size), 96.0)
        self.sprites, self.cell_width, self.cell_height = self.context.__enter__()

    @lru_cache(maxsize=512)
    def line(self, columns, runs):
        from kitty.fast_data_types import Screen, sprite_idx_to_pos, test_render_line
        screen = Screen(None, 1, columns)
        for text, bold in runs:
            screen.cursor.bold = bold
            screen.draw(text)
        line = screen.line(0)
        test_render_line(line)
        result = []
        for column in range(columns):
            sprite = line.sprite_at(column)
            position = sprite_idx_to_pos(sprite & 0x7fffffff, self.context.xnum, self.context.ynum)
            result.append((self.sprites[position], bool(sprite & 0x80000000)))
        return result

    @lru_cache(maxsize=8192)
    def cell(self, sprite, colored, foreground, background):
        # Kitty's native pixel is 0xRRGGBBAA: little-endian bytes A,B,G,R.
        table = palette(foreground, background)
        if not colored:
            return b"".join(table[alpha] for alpha in sprite[::4])
        bg = tuple(map(linear, rgb(background)))
        output = bytearray()
        for offset in range(0, len(sprite), 4):
            alpha = sprite[offset] / 255
            fg = (sprite[offset + 3], sprite[offset + 2], sprite[offset + 1])
            output.extend(srgb(linear(f) * alpha + b * (1 - alpha)) for f, b in zip(fg, bg))
        return bytes(output)

    def render(self, grid):
        lines = []
        for row in grid.cells:
            runs = []
            for cell in row:
                if not cell.text:
                    continue
                if runs and runs[-1][1] == cell.bold:
                    runs[-1] = (runs[-1][0] + cell.text, cell.bold)
                else:
                    runs.append((cell.text, cell.bold))
            sprites = self.line(grid.columns, tuple(runs))
            cells = [self.cell(*sprite, cell.color, cell.background) for sprite, cell in zip(sprites, row)]
            stride = self.cell_width * 3
            for pixel_row in range(self.cell_height):
                lines.append(b"".join(cell[pixel_row * stride:(pixel_row + 1) * stride] for cell in cells))
        return b"".join(lines)


def main():
    renderer = KittyRenderer()
    print(json.dumps({"ready": True, "cellWidth": renderer.cell_width, "cellHeight": renderer.cell_height}), flush=True)
    runtime = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    with tempfile.TemporaryDirectory(prefix="opencode-grid-", dir=runtime) as directory:
        generation = 0
        for line in sys.stdin:
            request = json.loads(line)
            started = time.monotonic()
            grid = grid_model.compose(request.get("sessions", []), request.get("catalog", {}),
                grid_model.COLUMNS, request["rows"], request.get("frame", 0), request.get("offset", 0),
                request.get("selected", -1), request.get("error", ""), character_border=request.get("characterBorder", False))
            width = grid.columns * renderer.cell_width
            height = grid.rows * renderer.cell_height
            path = Path(directory) / f"frame-{generation % 2}.png"
            data = png(width, height, renderer.render(grid))
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(data)
            temporary.replace(path)
            print(json.dumps({"path": str(path), "width": width, "height": height, "generation": generation,
                              "id": request.get("id"), "renderMs": (time.monotonic() - started) * 1000}), flush=True)
            generation += 1


if __name__ == "__main__":
    def terminate(_signal, _frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, terminate)
    main()
