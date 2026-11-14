"""Exercise actual installed GLSL with HDR + SDR multiple render targets.

Requires moderngl and numpy. Usage: python test-hdr-mirror.py LIBRARY [BASELINE]
The optional baseline proves the display output remains unchanged.
"""
import re
import sys
from pathlib import Path

import moderngl
import numpy as np


VERTEX = """#version 330 core
in vec2 pos; out vec2 v_texcoord;
void main() { v_texcoord=pos*.5+.5; gl_Position=vec4(pos,0,1); }
"""
ctx = moderngl.create_standalone_context(backend="egl", require=330)
quad = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], "f4").tobytes())


def shaders(path):
    texts = re.findall(rb"#version 300 es\nprecision highp float;[^\x00]+", Path(path).read_bytes())
    markers = {"apple": b"uniform vec2 dkfColorA;", "surface": b"uniform sampler2D bgTex;",
               "fitted": b"uniform int dockTooltip;"}
    return {name: next(s.decode() for s in texts if marker in s).replace(
        "#version 300 es\nprecision highp float;", "#version 330 core")
        for name, marker in markers.items()}


def render(source, name, linear, white, gamma22, alpha, marker=False):
    prog = ctx.program(vertex_shader=VERTEX, fragment_shader=source)
    vao = ctx.vertex_array(prog, [(quad, "2f", "pos")])
    targets = [ctx.texture((64, 64), 4, dtype="f4") for _ in range(2)]
    fb = ctx.framebuffer(targets)
    fb.use()
    fb.clear(.97, .03, .71, .19)
    settings = dict(workLinear=linear, workBlack=0, workWhite=white, sdrGamma22=gamma22,
                    opacity=.8, tex=0, texSmall=1, maskTex=2, bgTex=1,
                    maskUVOffset=(0, 0), maskUVScale=(1, 1),
                    fullSize=(64, 64), uvPadding=(0, 0), glassBoxOffsetPx=(8, 8),
                    glassBoxSizePx=(48, 48), cornerRadius=12, capA=1.1, capN=2.7,
                    pxScale=1, smallWeight=.15, chroma=1, refrW=8, refrP=2,
                    tangentParams=(1, 1, 1), rimL1=1, rimL2=2, rimK=1,
                    shadowKey=(.1, 0, 2), shadowAmb=(.1, 0, 3),
                    shapeRect=(8, 8, 48, 48), radii=(12, 12, 12, 12), px=1,
                    texOrigin=(0, 0), texSize=(64, 64), dispScale=(1, 1),
                    faceOpacity=1, clampLimit=1, placeholderAdditive=int(marker),
                    innerRefrInvH=1, outerRefrInvH=1, bleedInvH=1,
                    shadowInvH=1, shadowInvRadius=1, aberrInvH=1,
                    hlSpread=1, hlAmount=.5)
    for key, value in settings.items():
        if key in prog:
            prog[key].value = value
    if "faceCm" in prog:
        prog["faceCm"].write(np.array([[.6, 0, 0, .05], [0, .6, 0, .05], [0, 0, .6, .05]], "f4").tobytes())
    if "lut" in prog:
        prog["lut"].value = tuple(np.linspace(.13, .42, 17))

    def work(encoded):
        e = np.array(encoded)
        if not linear:
            return e
        l = e ** 2.2 if gamma22 else np.where(e <= .04045, e / 12.92, ((e + .055) / 1.055) ** 2.4)
        return l * white

    # Opaque glass backdrop; premultiplied client ink, including marker branch.
    ink = [124 / 255] * 3 if marker else [.9, .45, .2]
    background = np.r_[work([.5, .6, .7]), 1].astype("f4")
    surface = np.r_[work(ink) * alpha, alpha].astype("f4")
    textures = []
    for unit, pixel in enumerate([surface if name == "surface" else [.5, .6, .7, 1],
                                  background if name == "surface" else [.5, .6, .7, 1], surface]):
        tex = ctx.texture((64, 64), 4, np.tile(np.array(pixel, "f4"), (64, 64, 1)).tobytes(), dtype="f4")
        tex.build_mipmaps()
        tex.use(unit)
        textures.append(tex)
    vao.render(moderngl.TRIANGLE_STRIP)
    pixels = [np.frombuffer(fb.read(attachment=i, components=4, dtype="f4"), "f4").reshape(64, 64, 4).copy() for i in range(2)]
    for resource in [vao, prog, fb, *targets, *textures]:
        resource.release()
    return pixels


current = shaders(sys.argv[1])
baseline = shaders(sys.argv[2]) if len(sys.argv) > 2 else None
count = 0
for name, source in current.items():
    for linear, white, gamma22 in [(0, 1, 0), (1, .35, 0), (1, 4.375, 1)]:
        for alpha, marker in [(1, False), (.25, False), (.5, True)]:
            main, mirror = render(source, name, linear, white, gamma22, alpha, marker)
            assert np.isfinite(main).all() and np.isfinite(mirror).all(), name
            expected = main.copy()
            drawn = main[..., 3] != np.float32(.19)
            if linear:
                a = main[..., 3:4]
                l = np.maximum(main[..., :3] / np.where(a > 0, a, 1) / white, 0)
                converted = np.where(l <= .0031308, l * 12.92, 1.055 * l ** (1 / 2.4) - .055) * a
                expected[..., :3] = np.where(a > 0, converted, main[..., :3])
                expected[~drawn] = main[~drawn]
            error = np.max(np.abs(mirror - expected))
            worst = np.unravel_index(np.argmax(np.abs(mirror - expected)), main.shape)[:2]
            assert error < 2e-5, (name, linear, white, gamma22, alpha, marker, "capture error", error,
                                 worst, main[worst], mirror[worst], expected[worst])
            assert drawn.sum() > 100 and main[..., 3][drawn].max() > .1, (name, "empty fixture")
            if baseline:
                old, _ = render(baseline[name], name, linear, white, gamma22, alpha, marker)
                assert np.max(np.abs(main - old)) < 1e-6, (name, "display output changed")
            count += 1
    print(f"PASS: {name}: SDR/HDR, gamma 2.2, opacity, alpha and additive marker")
print(f"PASS: {count} MRT renders; capture output defined and SDR-encoded; display output preserved")
