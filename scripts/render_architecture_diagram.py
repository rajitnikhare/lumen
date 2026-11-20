"""Generates docs/architecture-diagram.png: Lumen's system architecture as an actual
flowchart (boxes + arrows), not just the monospace text version, using Lumen's real
brand colors from lumen/static/style.css. Drawn directly with Pillow rather than an
external diagramming tool, so it stays simple to regenerate if the architecture changes.

    .venv/bin/python scripts/render_architecture_diagram.py
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

GREEN = (0x2D, 0x5C, 0x48)
GREEN_SOFT = (0xEA, 0xF1, 0xED)
GOLD = (0xB3, 0x94, 0x61)
INK = (0x25, 0x36, 0x2F)
MUTED = (0x5B, 0x66, 0x60)
BG = (0xF7, 0xF8, 0xFA)
WHITE = (0xFF, 0xFF, 0xFF)

FONT_DIR = Path("/System/Library/Fonts/Supplemental")
WIDTH, HEIGHT = 1860, 1120


def font(name, size):
    return ImageFont.truetype(str(FONT_DIR / name), size)


def rounded_box(draw, box, *, fill, outline=None, width=2, radius=14):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def centered_text(draw, box, text, *, font_obj, fill, line_spacing=6):
    left, top, right, bottom = box
    lines = text.split("\n")
    heights = [draw.textbbox((0, 0), line, font=font_obj)[3] for line in lines]
    total_height = sum(heights) + line_spacing * (len(lines) - 1)
    y = top + ((bottom - top) - total_height) / 2
    for line, line_height in zip(lines, heights, strict=True):
        bbox = draw.textbbox((0, 0), line, font=font_obj)
        line_width = bbox[2] - bbox[0]
        x = left + ((right - left) - line_width) / 2
        draw.text((x, y), line, font=font_obj, fill=fill)
        y += line_height + line_spacing


def arrow(draw, start, end, *, color=GREEN, width=3, head=10):
    draw.line([start, end], fill=color, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    for offset in (0.4, -0.4):
        wing_angle = angle + math.pi + offset
        draw.line(
            [end, (end[0] + head * math.cos(wing_angle), end[1] + head * math.sin(wing_angle))],
            fill=color,
            width=width,
        )


def main():
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    label_font = font("Arial.ttf", 20)
    kicker_font = font("Arial Bold.ttf", 17)
    caption_font = font("Arial.ttf", 17)

    spine_left, spine_width = 70, 650
    spine_boxes = [
        "Mac application\nor loopback browser",
        "Session, origin, CSRF,\nand permission checks",
        "Explicit workflow controller",
        "Encrypted library +\nauthorized retrieval",
        "Local Ollama generation\n(loopback only, no cloud fallback)",
        "Citation-ID + lifecycle checks\n\u2192 encrypted, source-linked result",
    ]
    box_height, gap = 110, 36
    spine_tops = []
    y = 50
    for text in spine_boxes:
        box = (spine_left, y, spine_left + spine_width, y + box_height)
        rounded_box(draw, box, fill=GREEN)
        centered_text(draw, box, text, font_obj=label_font, fill=WHITE)
        spine_tops.append(box)
        y += box_height + gap

    for index in range(len(spine_boxes) - 1):
        box_a, box_b = spine_tops[index], spine_tops[index + 1]
        cx = spine_left + spine_width / 2
        arrow(draw, (cx, box_a[3]), (cx, box_b[1] - 4))

    controller_box = spine_tops[2]
    branch_left = spine_left + spine_width + 140
    branch_width = 630

    def branch(kicker, steps, start_y):
        draw.text((branch_left, start_y - 36), kicker.upper(), font=kicker_font, fill=GOLD)
        tops = []
        y_local = start_y
        for text in steps:
            box = (branch_left, y_local, branch_left + branch_width, y_local + 80)
            rounded_box(draw, box, fill=GREEN_SOFT, outline=GREEN, width=2)
            centered_text(draw, box, text, font_obj=label_font, fill=INK)
            tops.append(box)
            y_local += 80 + 26
        for i in range(len(tops) - 1):
            cx = branch_left + branch_width / 2
            arrow(draw, (cx, tops[i][3]), (cx, tops[i + 1][1] - 4), color=GREEN)
        return tops, y_local

    research_tops, research_end = branch(
        "Separately: approved research",
        [
            "Reviewed public query\n(explicit approval)",
            "One request to Brave Search",
            "Local comparison of snippets",
        ],
        start_y=controller_box[1] + 10,
    )
    mail_tops, _ = branch(
        "Separately: mail import",
        [
            "Explicit \u201cCheck for new mail\u201d click",
            "Read-only Gmail IMAP fetch",
            "Candidate reminders \u2192 explicit\naccept / edit / discard",
        ],
        start_y=research_end + 60,
    )

    controller_mid_y = (controller_box[1] + controller_box[3]) / 2
    for tops in (research_tops, mail_tops):
        first_box = tops[0]
        target_y = (first_box[1] + first_box[3]) / 2
        draw.line([(controller_box[2], controller_mid_y), (branch_left - 40, controller_mid_y)], fill=GOLD, width=3)
        draw.line([(branch_left - 40, controller_mid_y), (branch_left - 40, target_y)], fill=GOLD, width=3)
        arrow(draw, (branch_left - 40, target_y), (first_box[0] - 4, target_y), color=GOLD)

    caption = (
        "A deterministic application controller with task-specific local model calls \u2014 "
        "not a free-running planning loop or three cooperating agents."
    )
    draw.text((spine_left, HEIGHT - 55), caption, font=caption_font, fill=MUTED)

    output_path = Path("docs/architecture-diagram.png")
    img.save(output_path)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
