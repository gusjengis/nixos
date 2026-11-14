"""Actual installed surface shader: Trash artwork must never become additive ink.

python test-dock-ink.py NEW_LIBRARY OLD_LIBRARY [COMPARISON_PNG]
Requires moderngl, numpy, Pillow; headless EGL. Includes SDR/HDR and AA ink.
"""
from pathlib import Path
import re
import sys

import moderngl
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "theme/icons/MacOS-Native/64x64/places"
ctx = moderngl.create_standalone_context(backend="egl", require=330)
vertices = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], "f4").tobytes())
W, H, PAD, BODY_W = 354, 249, 80, 194
REGIONS = [(PAD/W, (PAD+80)/H, (PAD+BODY_W)/W, (PAD+86)/H),
           ((PAD+BODY_W-98)/W, (PAD+11)/H, (PAD+BODY_W-95)/W, (PAD+78)/H)]
VERTEX = """#version 330 core
in vec2 pos; out vec2 v_texcoord;
void main() { v_texcoord=pos*.5+.5; gl_Position=vec4(pos,0,1); }
"""


def shader(path):
    strings = re.findall(rb"#version 300 es\nprecision highp float;[^\x00]+", Path(path).read_bytes())
    return next(s.decode() for s in strings if b"uniform sampler2D bgTex;" in s).replace(
        "#version 300 es\nprecision highp float;", "#version 330 core")


def work(rgb, linear):
    if not linear:
        return rgb
    return np.where(rgb <= .04045, rgb/12.92, ((rgb+.055)/1.055)**2.4) * .35


def render(source, encoded, linear, restricted=True):
    p = ctx.program(vertex_shader=VERTEX, fragment_shader=source)
    vao = ctx.vertex_array(p, [(vertices, "2f", "pos")])
    a = encoded[..., 3:4]
    surface = np.concatenate((work(encoded[..., :3], linear)*a, a), axis=2).astype("f4")
    bg = np.tile(np.r_[work(np.array([.1, .2, .4]), linear), 1], (H, W, 1)).astype("f4")
    textures = [ctx.texture((W, H), 4, t.tobytes(), dtype="f4") for t in (surface, bg)]
    for unit, tex in enumerate(textures):
        tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        tex.use(unit)
    target = ctx.texture((W, H), 4, dtype="f4")
    fb = ctx.framebuffer([target])
    fb.use()
    fb.clear()
    for name, value in dict(tex=0, bgTex=1, maskUVOffset=(0, 0), maskUVScale=(1, 1),
                            opacity=1, placeholderAdditive=1, workLinear=int(linear),
                            workBlack=0, workWhite=.35 if linear else 1, sdrGamma22=0,
                            placeholderRectCount=2 if restricted else 0).items():
        if name in p:
            p[name].value = value
    if "placeholderRects" in p:
        p["placeholderRects"].value = REGIONS
    vao.render(moderngl.TRIANGLE_STRIP)
    result = np.frombuffer(fb.read(components=4, dtype="f4"), "f4").reshape(H, W, 4).copy()
    for resource in [vao, p, fb, target, *textures]:
        resource.release()
    return result, surface


new, old = map(shader, sys.argv[1:3])
assert "placeholderRectCount" in new
collisions = 0
for full in (False, True):
    image = np.asarray(Image.open(ASSETS / ("user-trash-full.png" if full else "user-trash.png"))
                       .convert("RGBA").resize((59, 59), Image.Resampling.LANCZOS), dtype="f4") / 255
    for held in (False, True):
        encoded = np.zeros((H, W, 4), "f4")
        icon = image.copy()
        if held:
            icon[..., :3] *= .7
        ys, xs = slice(PAD+14, PAD+73), slice(PAD+120, PAD+179)
        encoded[ys, xs] = icon
        # Coverage sweep in the actual dot band, separator with alpha 65/124.
        encoded[PAD+82, PAD+10:PAD+110, :3] = 124/255
        encoded[PAD+82, PAD+10:PAD+110, 3] = np.linspace(.02, 1, 100)
        encoded[PAD+12:PAD+77, PAD+97] = [124/255]*3 + [65/124]
        for linear in (False, True):
            result, expected = render(new, encoded, linear)
            baseline, _ = render(old, encoded, linear)
            if len(sys.argv) > 3 and full and held and not linear:
                def composite(tile):
                    return tile[..., :3] + (1-tile[..., 3:4])*[.1, .2, .4]
                contact = np.concatenate([composite(baseline[ys, xs]), composite(result[ys, xs])], axis=1)
                Image.fromarray(np.round(np.clip(contact, 0, 1)*255).astype("uint8")).resize(
                    (472, 236), Image.Resampling.NEAREST).save(sys.argv[3])
            assert np.max(np.abs(result[ys, xs] - expected[ys, xs])) < 2e-6, (full, held, linear)
            collisions += np.count_nonzero(np.max(np.abs(baseline[ys, xs] - expected[ys, xs]), axis=2) > .01)
            # Keep both additive primitives identical to old compositor output.
            assert np.max(np.abs(result[PAD+82] - baseline[PAD+82])) < 2e-6
            assert np.max(np.abs(result[PAD+12:PAD+77, PAD+97] - baseline[PAD+12:PAD+77, PAD+97])) < 2e-6
            # Other Apple surfaces (Spotlight) retain unrestricted marker behavior.
            unrestricted, _ = render(new, encoded, linear, restricted=False)
            assert np.max(np.abs(unrestricted - baseline)) < 2e-6
assert collisions > 0, "Baseline must reproduce real Trash marker collisions"
print(f"PASS: removed {collisions} actual Trash pixel collisions; empty/full, held/normal, SDR/HDR")
print("PASS: antialiased dots, separator and unrestricted launcher ink unchanged")
