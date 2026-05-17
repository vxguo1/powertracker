"""Generate the social-share image at app/og-image.png (1200x630).

Twitter, Facebook, LinkedIn, Slack and the like read og:image / twitter:image
out of the page <head>. Most of them reject SVG, so we ship a PNG. This is
purely brand-styled (wordmark + tagline + accent stripe + chips) -- no map
silhouette, no per-deploy data. Re-run only when the brand or copy changes.

    python scripts/build_og_image.py
"""

from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "og-image.png"

W, H = 1200, 630

# Brand palette (mirrors app/index.html design tokens).
BG = (255, 255, 255)
ACCENT = (215, 38, 61)        # #d7263d
INK = (26, 26, 35)             # #1a1a23
INK_MUTED = (90, 90, 110)      # #5a5a6e
INK_SOFT = (139, 139, 154)     # #8b8b9a
CHIP_BG = (238, 238, 243)      # #eeeef3
CHIP_INK = (90, 90, 110)
BORDER = (227, 227, 232)       # #e3e3e8

FONT_BOLD = "C:/Windows/Fonts/segoeuib.ttf"
FONT_REG = "C:/Windows/Fonts/segoeui.ttf"
FONT_SEMI = "C:/Windows/Fonts/segoeuisl.ttf"

CHIPS = [
    "AI data centers",
    "Grid demand",
    "Power infrastructure",
    "Rates & taxes",
    "Climate",
]


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def draw_bolt(d: ImageDraw.ImageDraw, x: int, y: int, scale: float = 1.0) -> None:
    """Render the favicon lightning-bolt polygon scaled into a 24x24 box."""
    pts_24 = [(13, 2), (3, 14), (12, 14), (11, 22), (21, 10), (12, 10), (13, 2)]
    pts = [(x + px * scale, y + py * scale) for (px, py) in pts_24]
    d.polygon(pts, fill=ACCENT)


def text_width(d: ImageDraw.ImageDraw, s: str, f: ImageFont.FreeTypeFont) -> int:
    l, t, r, b = d.textbbox((0, 0), s, font=f)
    return r - l


def text_height(d: ImageDraw.ImageDraw, s: str, f: ImageFont.FreeTypeFont) -> int:
    l, t, r, b = d.textbbox((0, 0), s, font=f)
    return b - t


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Left accent stripe (full height).
    d.rectangle([(0, 0), (12, H)], fill=ACCENT)

    # Bolt icon at top-left of content area.
    pad_x = 72
    bolt_top = 90
    draw_bolt(d, pad_x, bolt_top, scale=3.4)

    # Brand wordmark.
    f_brand = font(FONT_BOLD, 132)
    brand = "powertracker"
    brand_y = bolt_top + 110
    d.text((pad_x, brand_y), brand, font=f_brand, fill=INK)

    # Tagline (two lines).
    f_tag = font(FONT_SEMI, 38)
    tag_y = brand_y + text_height(d, brand, f_brand) + 36
    line1 = "AI & hyperscaler data centers,"
    line2 = "and the US grid context around them"
    d.text((pad_x, tag_y), line1, font=f_tag, fill=INK_MUTED)
    d.text(
        (pad_x, tag_y + text_height(d, line1, f_tag) + 10),
        line2,
        font=f_tag,
        fill=INK_MUTED,
    )

    # Topic chips along a single row.
    f_chip = font(FONT_BOLD, 22)
    chip_y = H - 150
    chip_pad_x = 22
    chip_pad_y = 12
    chip_gap = 14
    cursor_x = pad_x
    for label in CHIPS:
        tw = text_width(d, label, f_chip)
        th = text_height(d, label, f_chip)
        chip_w = tw + chip_pad_x * 2
        chip_h = th + chip_pad_y * 2 + 6
        d.rounded_rectangle(
            [(cursor_x, chip_y), (cursor_x + chip_w, chip_y + chip_h)],
            radius=chip_h // 2,
            fill=CHIP_BG,
        )
        d.text(
            (cursor_x + chip_pad_x, chip_y + chip_pad_y),
            label,
            font=f_chip,
            fill=CHIP_INK,
        )
        cursor_x += chip_w + chip_gap

    # URL bottom-right + thin baseline rule.
    f_url = font(FONT_BOLD, 26)
    url = "powertracker.io"
    uw = text_width(d, url, f_url)
    d.text((W - uw - pad_x, H - 70), url, font=f_url, fill=ACCENT)

    d.rectangle([(0, H - 8), (W, H)], fill=ACCENT)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
