"""Generates Lumen's logo as an actual image, matching the brand mark defined in
lumen/static/style.css (`.brand-mark`, `.brand`, `.brand-period`) rather than a
redrawn approximation. There is no existing logo image file anywhere in the
project; the brand mark only exists as CSS + an "L" character in the HTML.

    .venv/bin/python scripts/render_logo.py

Writes two images to docs/:
  - logo-mark.png: the green rounded-square mark alone (for a favicon-style use).
  - logo.png: the mark paired with the "lumen." wordmark, for the README header.

Both are rendered at a high scale factor with a transparent background so they
read cleanly on both light and dark backgrounds.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

GREEN = (0x2D, 0x5C, 0x48)
INK = (0x26, 0x3B, 0x30)
PERIOD_GOLD = (0xAC, 0xBB, 0x9D)
WHITE = (0xFF, 0xFF, 0xFF)
SHADOW = (0x24, 0x4B, 0x39)

FONT_DIR = Path("/System/Library/Fonts/Supplemental")
OUTPUT_DIR = Path("docs")

# CSS .brand-mark is a 53x53px box with a 17px border-radius (a ratio of ~0.32)
# and a 35px Georgia "L"; everything below scales that up for crispness.
SCALE = 8
MARK_SIZE = 53 * SCALE
MARK_RADIUS = 17 * SCALE
LETTER_SIZE = 35 * SCALE


def font(name, size):
    return ImageFont.truetype(str(FONT_DIR / name), size)


def centered_text(draw, box, text, *, font_obj, fill):
    left, top, right, bottom = box
    bbox = draw.textbbox((0, 0), text, font=font_obj)
    width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = left + ((right - left) - width) / 2 - bbox[0]
    y = top + ((bottom - top) - height) / 2 - bbox[1]
    draw.text((x, y), text, font=font_obj, fill=fill)


def draw_mark(size=MARK_SIZE, radius=MARK_RADIUS, letter_size=LETTER_SIZE, *, shadow=True):
    """Draws the brand mark (green rounded square + white "L") onto a padded,
    transparent canvas, matching `.brand-mark{border-radius:17px;background:var(--green);
    color:#fff;font-family:Georgia,serif;font-size:35px;box-shadow:0 4px 12px #244b3912}`.
    """
    pad = size // 3
    canvas = Image.new("RGBA", (size + pad * 2, size + pad * 2), (0, 0, 0, 0))

    if shadow:
        shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        offset = size // 20
        shadow_draw.rounded_rectangle(
            (pad, pad + offset, pad + size, pad + size + offset),
            radius=radius,
            fill=(*SHADOW, 40),
        )
        canvas = Image.alpha_composite(canvas, shadow_layer.filter(ImageFilter.GaussianBlur(size // 18)))

    draw = ImageDraw.Draw(canvas)
    box = (pad, pad, pad + size, pad + size)
    draw.rounded_rectangle(box, radius=radius, fill=(*GREEN, 255))
    centered_text(draw, box, "L", font_obj=font("Georgia.ttf", letter_size), fill=WHITE)
    return canvas, pad


def render_mark_only():
    canvas, pad = draw_mark()
    canvas = canvas.crop((pad, pad, canvas.width - pad, canvas.height - pad))
    out = OUTPUT_DIR / "logo-mark.png"
    canvas.save(out)
    print(f"Wrote {out}")


def render_wordmark():
    # `.brand`: font-size 30px, letter-spacing -1px, color #263b30, font-weight 650,
    # gap 10px between mark and text; `.brand-period`: color #acbb9d.
    mark, mark_pad = draw_mark(shadow=False)
    mark = mark.crop((mark_pad, mark_pad, mark.width - mark_pad, mark.height - mark_pad))

    word_font = font("Arial Bold.ttf", 30 * SCALE)
    gap = 10 * SCALE
    margin = 20 * SCALE

    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lumen_box = probe.textbbox((0, 0), "lumen", font=word_font)
    period_box = probe.textbbox((0, 0), ".", font=word_font)
    lumen_w, lumen_h = lumen_box[2] - lumen_box[0], lumen_box[3] - lumen_box[1]
    period_w = period_box[2] - period_box[0]

    height = max(mark.height, lumen_h) + margin * 2
    width = mark.width + gap + lumen_w + period_w + margin * 2
    canvas = Image.new("RGBA", (int(width), int(height)), (0, 0, 0, 0))

    mark_y = (height - mark.height) // 2
    canvas.alpha_composite(mark, (margin, int(mark_y)))

    draw = ImageDraw.Draw(canvas)
    text_x = margin + mark.width + gap
    text_y = (height - lumen_h) / 2 - lumen_box[1]
    draw.text((text_x, text_y), "lumen", font=word_font, fill=INK)
    draw.text((text_x + lumen_w, text_y), ".", font=word_font, fill=PERIOD_GOLD)

    out = OUTPUT_DIR / "logo.png"
    bbox = canvas.getbbox()
    pad = margin // 2
    trimmed = canvas.crop((bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad))
    trimmed.save(out)
    print(f"Wrote {out}")


def main():
    render_mark_only()
    render_wordmark()


if __name__ == "__main__":
    main()
