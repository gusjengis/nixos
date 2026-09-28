Darwin Plymouth artwork (`logo.png`, `progress_box.png`, `progress_bar.png`) is
from https://github.com/libredeb/darwin-plymouth by Lozano Juan Pablo, GPL-3.0.
`grub/background.png` is generated from that logo on a black 1920x1200 canvas.
GRUB scales the hidden-timeout image to the EFI framebuffer; its menu theme
scales the same image proportionally to the display height. On non-16:10
screens the brief hidden image can stretch horizontally.
