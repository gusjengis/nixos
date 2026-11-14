"""Render the installed tooltip shader against archived macOS label captures.

Run in an environment with moderngl, numpy and pillow:
    python test-dock-tooltip.py LIBRARY REFERENCE_DIR OUTPUT_DIR
REFERENCE_DIR is MacOS Theme/26-dock/mac. Output contains enlarged evidence.
"""
import re
import sys
from pathlib import Path

import moderngl
import numpy as np
from PIL import Image

library, references, output = map(Path, sys.argv[1:])
output.mkdir(parents=True, exist_ok=True)
binary = library.read_bytes()
shaders = re.findall(rb'#version 300 es\nprecision highp float;[^\x00]+', binary)
fragment = next(s.decode() for s in shaders if b'uniform int dockTooltip;' in s)
fragment = fragment.replace('#version 300 es\nprecision highp float;', '#version 330 core')
vertex = '''#version 330 core
in vec2 pos; out vec2 v_texcoord;
void main() { v_texcoord = vec2(pos.x*.5+.5, .5-pos.y*.5); gl_Position=vec4(pos,0,1); }
'''
ctx = moderngl.create_standalone_context(backend='egl', require=330)
prog = ctx.program(vertex_shader=vertex, fragment_shader=fragment)
quad = ctx.buffer(np.array([-1,-1,1,-1,-1,1,1,1], dtype='f4').tobytes())
vao = ctx.vertex_array(prog, [(quad, '2f', 'pos')])
w, h = 180, 65
target = ctx.simple_framebuffer((w,h), components=4)
target.use()

def uniform(name, value):
    if name in prog:
        prog[name].value = value

settings = dict(fullSize=(w,h), uvPadding=(0,0), glassBoxOffsetPx=(26,11),
                glassBoxSizePx=(127,33), cornerRadius=13, capA=1.1, capN=2.7,
                pxScale=1, dockTooltip=1, smallWeight=.15, chroma=1,
                refrA=0, refrW=8, refrP=2, tangentStrength=0, tangentParams=(1,1,1),
                rimR0=.353, rimRC=.835, rimA1=.715, rimL1=.333, rimL2=2.47,
                rimSide=.04, rimK=13.7, outlineAlpha=.6*.72, outlineSidePower=2,
                shadowKey=(0,0,1), shadowAmb=(0,0,1), opacity=1,
                maskUVOffset=(0,0), maskUVScale=(1,1), tex=0, texSmall=1, maskTex=2)
for key, value in settings.items():
    uniform(key, value)
uniform('lut', (.1294,.1578,.1849,.2105,.2347,.2576,.2790,.2990,.3176,
                .3348,.3507,.3651,.3781,.3897,.3999,.4087,.4144))
mask = ctx.texture((w,h),4,bytes(w*h*4)); mask.use(2)
for gray, name in [(0,'black'),(128,'gray'),(255,'white')]:
    background = ctx.texture((w,h),3,bytes([gray])*(w*h*3))
    background.use(0); background.use(1)
    target.clear(); vao.render(moderngl.TRIANGLE_STRIP)
    rgba = np.frombuffer(target.read(components=4),np.uint8).reshape(h,w,4)[::-1]
    alpha = rgba[:,:,3:4].astype(float)/255
    result = np.round(rgba[:,:,:3] + gray*(1-alpha)).clip(0,255).astype('uint8')
    ref = np.asarray(Image.open(references/f'hover-{name}.png').convert('RGB'))[120:185,378:558]
    # Compare edges and pointer, excluding text and Dock below y=166.
    selection = np.zeros((h,w),bool)
    selection[10:41,20:42] = True
    selection[10:41,137:160] = True
    selection[36:45,65:115] = True
    error = np.abs(result.astype(float)-ref.astype(float)).mean(2)
    print(f'{name}: shape/rim/pointer MAE {error[selection].mean():.2f}/255')
    assert error[selection].mean() < 9, 'Label contour/material deviates from Mac reference'
    Image.fromarray(result[:47]).resize((1080,282)).save(output/f'tooltip-{name}.png')
    Image.fromarray(ref[:47]).resize((1080,282)).save(output/f'mac-{name}.png')
print('PASS: installed GLSL compiles; capsule and pointer match three Mac backdrops')
