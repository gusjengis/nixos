"""Compare the installed Dock menu silhouette with a macOS 27 capture.

Run in an environment with moderngl, numpy and pillow:
    python test-dock-menu.py LIBRARY REFERENCE_PGM OUTPUT_DIR
REFERENCE_PGM is the 120x60 grayscale 2x crop of the Mac Trash Dock menu at
(2173,2420) (MacOS Theme/29-dock-menu/mac/trash-pointer-2x.pgm). The body's
left edge is at x=6.3 and its bottom at y=23.5; the pointer tip is 27 pt
right of the body edge. The dark rim marks the Mac silhouette.
"""
import re
import sys
from pathlib import Path

import moderngl
import numpy as np
from PIL import Image

library, reference, output = map(Path, sys.argv[1:])
output.mkdir(parents=True, exist_ok=True)
binary = library.read_bytes()
shaders = re.findall(rb'#version 300 es\nprecision highp float;[^\x00]+', binary)
fragment = next(s.decode() for s in shaders if b'uniform vec2 callout;' in s)
fragment = fragment.replace('#version 300 es\nprecision highp float;', '#version 330 core')
vertex = '''#version 330 core
in vec2 pos;
void main() { gl_Position = vec4(pos, 0, 1); }
'''
ctx = moderngl.create_standalone_context(backend='egl', require=330)
prog = ctx.program(vertex_shader=vertex, fragment_shader=fragment)
quad = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype='f4').tobytes())
vao = ctx.vertex_array(prog, [(quad, '2f', 'pos')])
w, h = 120, 60
backdrop = ctx.texture((64, 64), 4, np.full((64, 64, 4), 128, np.uint8).tobytes())
backdrop.build_mipmaps()
backdrop.use(0)

scale = 2.0
body_height = 69 * scale
settings = dict(tex=0, texOrigin=(-200, -400), texSize=(600, 600), px=scale,
                shapeRect=(6.3, 23.5 - body_height, 108 * scale, body_height + 10 * scale),
                radii=(26, 26, 26, 26), opacity=1.0, continuousCorners=1,
                callout=(27.0, 10.0), dispScale=(0, 0), faceCm=[(1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0)],
                bleedCm=[(1, 0, 0, 0)] * 3, shadowCm=[(0, 0, 0, 0)] * 3, dkfCm=[(1, 0, 0, 0)] * 3,
                workBlack=0.0, workWhite=1.0)
for name, value in settings.items():
    if name in prog:
        prog[name].value = value

target = ctx.simple_framebuffer((w, h), components=4, dtype='f4')
target.use()
target.clear()
vao.render(moderngl.TRIANGLE_STRIP)
# Raw rows follow gl_FragCoord.y, which the shader treats as top-down.
alpha = np.frombuffer(target.read(components=4, dtype='f4'), 'f4').reshape(h, w, 4)[..., 3]

tokens = reference.read_text().split()
mac = np.array(tokens[4:], float).reshape(int(tokens[2]), int(tokens[1]))


def crossing(values, start, stop, step):
    for x in range(start, stop, step):
        a, b = values[x], values[x + step]
        if (a - 0.5) * (b - 0.5) <= 0 and a != b:
            return x + step * (0.5 - a) / (b - a)
    return None


errors = []
for y in range(25, 43):
    row = mac[y]
    mac_left = 30 + int(np.argmin(row[30:58]))
    mac_right = 59 + int(np.argmin(row[59:96]))
    ours_left = crossing(alpha[y], 30, 58, 1)
    ours_right = crossing(alpha[y], 96, 59, -1)
    if ours_left is None or ours_right is None:
        sys.exit(f'FAIL: row {y} has no pointer edge')
    # Both are pixel indices; report the error in pt.
    errors += [(ours_left - mac_left) / scale, (ours_right - mac_right) / scale]
errors = np.abs(errors)
print(f'pointer contour error: mean {errors.mean():.2f} pt, max {errors.max():.2f} pt')

overlay = np.stack([mac] * 3, -1).astype(np.uint8)
edge = (alpha > 0.1) & (alpha < 0.9)
overlay[edge] = (255, 0, 0)
Image.fromarray(overlay).resize((w * 8, h * 8), Image.NEAREST).save(output / 'dock-menu-pointer.png')
if errors.max() > 1.0:
    sys.exit('FAIL: pointer contour differs from macOS by more than 1 pt')
print('PASS: installed GLSL compiles; pointer contour matches the Mac capture')
