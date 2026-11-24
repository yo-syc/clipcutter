"""Draw the app icon and write icon.png, icon.ico (Windows) and, on macOS, icon.icns."""
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
OUT = HERE / "build"


def draw(size: int = 1024) -> Image.Image:
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    m = size // 10
    d.rounded_rectangle((m, m, size - m, size - m), radius=size // 5, fill=(14, 14, 18, 255))
    # a 9:16 frame with a yellow "cut" through it
    fw, fh = size * 0.34, size * 0.60
    x0, y0 = (size - fw) / 2, (size - fh) / 2
    d.rounded_rectangle((x0, y0, x0 + fw, y0 + fh), radius=size // 28, outline=(242, 242, 245, 255), width=size // 34)
    d.polygon([(x0 - size * .10, y0 + fh * .62), (x0 + fw + size * .10, y0 + fh * .38),
               (x0 + fw + size * .10, y0 + fh * .38 + size * .07), (x0 - size * .10, y0 + fh * .62 + size * .07)],
              fill=(255, 230, 0, 255))
    cx, cy, r = size / 2, y0 + fh * .30, size * .07   # play button
    d.polygon([(cx - r * .8, cy - r), (cx - r * .8, cy + r), (cx + r, cy)], fill=(255, 230, 0, 255))
    return im


def main() -> None:
    OUT.mkdir(exist_ok=True)
    im = draw()
    im.save(OUT / "icon.png")
    im.save(OUT / "icon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    if sys.platform == "darwin":
        iconset = OUT / "icon.iconset"
        shutil.rmtree(iconset, ignore_errors=True)
        iconset.mkdir()
        for s in (16, 32, 128, 256, 512):
            im.resize((s, s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
            im.resize((s * 2, s * 2), Image.LANCZOS).save(iconset / f"icon_{s}x{s}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT / "icon.icns")], check=True)
    print("icons in", OUT)


if __name__ == "__main__":
    main()
