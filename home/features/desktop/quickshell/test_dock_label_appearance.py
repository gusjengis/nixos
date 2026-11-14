"""Compare the real DockLabel fixture against archived Mac label typography.

Generate RENDER with test_dock_label_render.qml, then run:
    python test_dock_label_appearance.py MAC_REFERENCE_DIR RENDER OUTPUT_DIR
Requires numpy and Pillow. Comparisons use fixed placement and text color;
there is no per-image width scaling, position search or fitted opacity.
"""
from pathlib import Path
import sys

import numpy as np
from PIL import Image

references, render_path, output = map(Path, sys.argv[1:])
output.mkdir(parents=True, exist_ok=True)
render = np.asarray(Image.open(render_path).convert("RGB")).mean(2)
old_alpha = (render[13:34, 7:122] - 82) / 173
new_alpha = (render[53:74, 7:122] - 82) / 173
for name in ("black", "gray", "white"):
    ref = np.asarray(Image.open(references / f"hover-{name}.png").convert("RGB")).mean(2)
    # A text-free inner padding strip supplies the body's row-dependent tone.
    base = ref[135:156, 414:416].mean(1)[:, None]
    target = np.maximum((ref[135:156, 410:525] - base) / (255 - base), 0)
    old_error = np.sqrt(np.mean((old_alpha - target) ** 2))
    new_error = np.sqrt(np.mean((new_alpha - target) ** 2))
    print(f"{name}: old/new text coverage RMS {old_error:.4f}/{new_error:.4f}; "
          f"reduction {100 * (1-new_error/old_error):.1f}%")
    assert new_error < .7 * old_error, "Typography must substantially improve on old label"
    contact = np.concatenate([ref[135:156,410:525],
                              base + old_alpha * (255-base),
                              base + new_alpha * (255-base)], axis=0)
    Image.fromarray(np.round(contact).clip(0,255).astype("uint8")).resize((920,504)).save(output/f"text-{name}.png")
print("PASS: fixed-placement DockLabel improves text appearance across three Mac backdrops")
