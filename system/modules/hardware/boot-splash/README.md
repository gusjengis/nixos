Darwin Plymouth artwork (`logo.png`, `progress_box.png`, `progress_bar.png`) is
from https://github.com/libredeb/darwin-plymouth by Lozano Juan Pablo, GPL-3.0.
The GRUB countdown is black because GRUB cannot center a fixed-pixel bitmap
during its hidden timeout. Plymouth centers fixed-size artwork on any display:
its Apple is approximately 86x106 visible pixels, with a 200x16 progress track.
