"""Draws the EduSignal mark (same geometry as frontend/assets/logo_mark.svg) into the
Android and iOS icon/splash files. Run from the mobile project root:  python scripts/make_icons.py"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "android/app/src/main/res"
INK, GOLD, SPLASH_BG = (31, 42, 48, 255), (245, 183, 0, 255), (247, 248, 246, 255)
BARS = [(14, 36, 14, 140), (28, 27, 23, 204), (42, 18, 32, 255)]   # x, y, height, alpha (64-unit grid)
S = 16  # supersampling factor


def mark(size: int, tile: str | None, content: float = 1.0) -> Image.Image:
    """tile: 'rounded' | 'circle' | 'square' | None (transparent). content: share of the canvas the 64-grid uses."""
    big = size * S
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if tile == "rounded":
        d.rounded_rectangle([0, 0, big - 1, big - 1], radius=big * 15 / 64, fill=INK)
    elif tile == "circle":
        d.ellipse([0, 0, big - 1, big - 1], fill=INK)
    elif tile == "square":
        d.rectangle([0, 0, big, big], fill=INK)
    u = big * content / 64
    off = (big - 64 * u) / 2
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    o = ImageDraw.Draw(overlay)
    for x, y, h, a in BARS:
        o.rounded_rectangle([off + x * u, off + y * u, off + (x + 8) * u, off + (y + h) * u],
                            radius=2.5 * u, fill=(255, 255, 255, a))
    o.ellipse([off + 42 * u, off + 6.5 * u, off + 50 * u, off + 14.5 * u], fill=GOLD)
    img = Image.alpha_composite(img, overlay)
    return img.resize((size, size), Image.LANCZOS)


# Android launcher icons
for folder, legacy, fg in [("mdpi", 48, 108), ("hdpi", 72, 162), ("xhdpi", 96, 216),
                           ("xxhdpi", 144, 324), ("xxxhdpi", 192, 432)]:
    d = RES / f"mipmap-{folder}"
    mark(legacy, "rounded", 0.82).save(d / "ic_launcher.png")
    mark(legacy, "circle", 0.72).save(d / "ic_launcher_round.png")
    mark(fg, None, 0.52).save(d / "ic_launcher_foreground.png")   # adaptive icon: keep inside the 66/108 safe zone
(RES / "values/ic_launcher_background.xml").write_text(
    '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
    '    <color name="ic_launcher_background">#1F2A30</color>\n</resources>\n', encoding="utf-8")

# Android splash screens: logo tile centred on the app's light background, same sizes as the template
for p in RES.glob("drawable*/splash.png"):
    w, h = Image.open(p).size
    canvas = Image.new("RGBA", (w, h), SPLASH_BG)
    side = int(min(w, h) * 0.28)
    canvas.alpha_composite(mark(side, "rounded", 1.0), ((w - side) // 2, (h - side) // 2))
    canvas.convert("RGB").save(p)

# iOS app icon (1024, opaque, iOS applies its own corner mask)
ios_icon = ROOT / "ios/App/App/Assets.xcassets/AppIcon.appiconset/AppIcon-512@2x.png"
mark(1024, "square", 0.82).convert("RGB").save(ios_icon)

# iOS splash images
for p in (ROOT / "ios/App/App/Assets.xcassets/Splash.imageset").glob("*.png"):
    w, h = Image.open(p).size
    canvas = Image.new("RGBA", (w, h), SPLASH_BG)
    side = int(min(w, h) * 0.28)
    canvas.alpha_composite(mark(side, "rounded", 1.0), ((w - side) // 2, (h - side) // 2))
    canvas.convert("RGB").save(p)

mark(512, "rounded", 1.0).save(ROOT / "resources/icon-preview.png")
print("icons written")
