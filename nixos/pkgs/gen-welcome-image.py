"""Generate the boot splash image headers from images/welcome.png.

    python3 nixos/pkgs/gen-welcome-image.py            # writes both headers
    python3 nixos/pkgs/gen-welcome-image.py --check    # compare, write nothing

welcome_image.h is 128x128 (SSD1351, rev 3); welcome_image_176.h is
176x176 (SSD1333, v4). The image is scaled the same way the app's splash.py
scales it (PIL resize, default resampling), so both splashes match. Pixels are
RGB565 of the channel-swapped image, as splash.py sends it (bgr panels).
"""

import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent.parent / "images" / "welcome.png"
TARGETS = {
    128: ("welcome_image.h", "welcome_image"),
    176: ("welcome_image_176.h", "welcome_image_176"),
}


def header(size: int, name: str) -> str:
    img = Image.open(SOURCE).convert("RGB")
    if img.size != (size, size):
        img = img.resize((size, size))
    raw = img.tobytes()
    pixels = []
    for i in range(0, len(raw), 3):
        # splash.py reverses the channels before the (bgr) panel sees them.
        b, g, r = raw[i], raw[i + 1], raw[i + 2]
        pixels.append(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3))
    lines = [
        f"// Auto-generated from welcome.png - {size}x{size} BGR565",
        f"static const uint16_t {name}[{size * size}] = {{",
    ]
    for i in range(0, len(pixels), 16):
        row = ", ".join(f"0x{p:04X}" for p in pixels[i : i + 16])
        lines.append(f"    {row},")
    lines.append("};")
    return "\n".join(lines) + "\n"


def main() -> int:
    check = "--check" in sys.argv
    ok = True
    for size, (fname, name) in TARGETS.items():
        text = header(size, name)
        path = HERE / fname
        if check:
            same = path.exists() and path.read_text() == text
            print(f"{fname}: {'matches' if same else 'DIFFERS'}")
            ok &= same
        else:
            path.write_text(text)
            print(f"wrote {fname}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
