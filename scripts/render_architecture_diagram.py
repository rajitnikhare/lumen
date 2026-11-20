"""Generates Lumen's architecture diagrams as actual flowcharts (boxes + arrows), not
just monospace text, using Lumen's real brand colors from lumen/static/style.css. Drawn
directly with Pillow rather than an external diagramming tool, so they stay simple to
regenerate if the architecture changes.

    .venv/bin/python scripts/render_architecture_diagram.py

Writes three images to docs/:
  - architecture-diagram.png: the main request flow plus the research/mail branches.
  - component-diagram.png: which process/module owns what, and which modules reach
    the network (and under what restriction).
  - permission-lifecycle-diagram.png: how a record moves between private, authorized,
    and deleted, and how locking/revocation cut it off.
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
OUTPUT_DIR = Path("docs")


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


def label_above(draw, xy, text, *, font_obj, fill=GOLD, center=True):
    x, y = xy
    if center:
        bbox = draw.textbbox((0, 0), text, font=font_obj)
        x -= (bbox[2] - bbox[0]) / 2
    draw.text((x, y), text, font=font_obj, fill=fill)


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


def right_angle_connector(draw, points, *, color=GOLD, width=3, head=10):
    """Draws a connector through the given waypoints; only the final leg gets an arrowhead."""
    for i in range(len(points) - 2):
        draw.line([points[i], points[i + 1]], fill=color, width=width)
    arrow(draw, points[-2], points[-1], color=color, width=width, head=head)


def save(img, name):
    output_path = OUTPUT_DIR / name
    img.save(output_path)
    print(f"Wrote {output_path}")


def render_request_flow_diagram():
    width, height = 1860, 1120
    img = Image.new("RGB", (width, height), BG)
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
    draw.text((spine_left, height - 55), caption, font=caption_font, fill=MUTED)
    save(img, "architecture-diagram.png")


def render_component_diagram():
    width, height = 1860, 860
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    label_font = font("Arial.ttf", 19)
    small_font = font("Arial.ttf", 16)
    caption_font = font("Arial.ttf", 17)

    margin = 70
    top_width = 520
    native_box = (margin, 40, margin + top_width, 40 + 90)
    browser_box = (width - margin - top_width, 40, width - margin, 40 + 90)
    rounded_box(draw, native_box, fill=GREEN)
    centered_text(draw, native_box, "Native Mac app (Swift/AppKit)\nmenu bar, sharing, dictation", font_obj=label_font, fill=WHITE)
    rounded_box(draw, browser_box, fill=GREEN)
    centered_text(draw, browser_box, "Loopback browser\n(http://127.0.0.1 only)", font_obj=label_font, fill=WHITE)

    lifecycle_box = (margin, 170, margin + top_width, 170 + 80)
    rounded_box(draw, lifecycle_box, fill=GREEN_SOFT, outline=GREEN, width=2)
    centered_text(draw, lifecycle_box, "desktop_server.py\nowns the backend process lifecycle", font_obj=small_font, fill=INK)
    arrow(draw, (margin + top_width / 2, native_box[3]), (margin + top_width / 2, lifecycle_box[1] - 4))

    controller_box = (width // 2 - 420, 300, width // 2 + 420, 300 + 100)
    rounded_box(draw, controller_box, fill=GREEN)
    centered_text(draw, controller_box, "lumen/app.py \u2014 controller\nsessions, permissions, approvals, workflows", font_obj=label_font, fill=WHITE)
    arrow(draw, (margin + top_width / 2, lifecycle_box[3]), ((controller_box[0] + 120), controller_box[1] - 4))
    arrow(draw, (width - margin - top_width / 2, browser_box[3]), (controller_box[2] - 120, controller_box[1] - 4))

    modules = [
        ("storage.py", "Encrypted SQLite vault\n(AES-256-GCM)"),
        ("documents.py", "Extraction, chunking,\nretrieval"),
        ("inference.py", "Loopback Ollama client"),
        ("research.py", "Approved Brave\nSearch calls"),
        ("mail.py", "Read-only Gmail\nIMAP fetch"),
        ("static/", "Browser UI\n(HTML/CSS/JS)"),
    ]
    module_y = 460
    module_height = 110
    module_gap = 22
    module_width = (width - 2 * margin - module_gap * (len(modules) - 1)) / len(modules)
    module_boxes = []
    controller_cx = (controller_box[0] + controller_box[2]) / 2
    for index, (name, desc) in enumerate(modules):
        x = margin + index * (module_width + module_gap)
        box = (x, module_y, x + module_width, module_y + module_height)
        rounded_box(draw, box, fill=GREEN_SOFT, outline=GREEN, width=2)
        centered_text(draw, box, f"{name}\n{desc}", font_obj=small_font, fill=INK)
        module_boxes.append(box)
        cx = x + module_width / 2
        arrow(draw, (controller_cx, controller_box[3]), (cx, box[1] - 4), color=GREEN)

    network_specs = {
        2: "Ollama\n127.0.0.1:11434\n(loopback only, never cloud)",
        3: "Brave Search API\n(only after explicit\nper-query approval)",
        4: "Gmail IMAP\n(only on explicit\n\u201cCheck for new mail\u201d click)",
    }
    network_y = 650
    network_height = 130
    for index, text in network_specs.items():
        box = module_boxes[index]
        cx = (box[0] + box[2]) / 2
        net_box = (box[0], network_y, box[2], network_y + network_height)
        rounded_box(draw, net_box, fill=WHITE, outline=GOLD, width=2)
        centered_text(draw, net_box, text, font_obj=small_font, fill=INK)
        arrow(draw, (cx, box[3]), (cx, net_box[1] - 4), color=GOLD)

    caption = (
        "Every network-reaching module is restricted (loopback-only, approval-gated, or explicit-trigger-only) \u2014 "
        "storage.py and documents.py never reach the network at all."
    )
    draw.text((margin, height - 45), caption, font=caption_font, fill=MUTED)
    save(img, "component-diagram.png")


def render_permission_lifecycle_diagram():
    width, height = 1860, 760
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    label_font = font("Arial.ttf", 19)
    small_font = font("Arial.ttf", 15)
    caption_font = font("Arial.ttf", 17)

    box_width, gap, box_height = 390, 60, 130
    top_y = 60
    labels = [
        "Vault locked",
        "Vault unlocked\n(passphrase verified)",
        "Record created or imported\n(private by default)",
        "Explicitly authorized\n(eligible for AI retrieval)",
    ]
    boxes = []
    x = 80
    for text in labels:
        box = (x, top_y, x + box_width, top_y + box_height)
        rounded_box(draw, box, fill=GREEN)
        centered_text(draw, box, text, font_obj=label_font, fill=WHITE)
        boxes.append(box)
        x += box_width + gap

    step_labels = ["unlock", "save / import", "explicit authorize"]
    for i, text in enumerate(step_labels):
        cy = (boxes[i][1] + boxes[i][3]) / 2
        arrow(draw, (boxes[i][2], cy), (boxes[i + 1][0] - 4, cy))
        label_above(draw, ((boxes[i][2] + boxes[i + 1][0]) / 2, boxes[i][1] - 30), text.upper(), font_obj=small_font, fill=MUTED)

    # Revoke: authorized -> back to private, excluded immediately.
    revoke_y = boxes[3][3] + 70
    revoke_points = [
        (boxes[3][0] + box_width * 0.3, boxes[3][3]),
        (boxes[3][0] + box_width * 0.3, revoke_y),
        (boxes[2][0] + box_width * 0.7, revoke_y),
        (boxes[2][0] + box_width * 0.7, boxes[2][3] + 4),
    ]
    right_angle_connector(draw, revoke_points, color=GOLD)
    label_above(draw, ((revoke_points[1][0] + revoke_points[2][0]) / 2, revoke_y - 32), "EXPLICIT REVOKE \u2014 excluded immediately, even mid-request", font_obj=small_font, fill=GOLD)

    # Lock: unlocked -> back to locked, clears approvals.
    lock_y = revoke_y + 90
    lock_points = [
        (boxes[1][0] + box_width * 0.3, boxes[1][3]),
        (boxes[1][0] + box_width * 0.3, lock_y),
        (boxes[0][0] + box_width * 0.7, lock_y),
        (boxes[0][0] + box_width * 0.7, boxes[0][3] + 4),
    ]
    right_angle_connector(draw, lock_points, color=GOLD)
    label_above(draw, ((lock_points[1][0] + lock_points[2][0]) / 2, lock_y - 32), "LOCK (ANYTIME) \u2014 clears approvals, discards in-flight work", font_obj=small_font, fill=GOLD)

    # Deletion: both private and authorized records can be deleted via a single-use approval.
    delete_y = lock_y + 110
    approval_box = (boxes[2][0], delete_y, boxes[3][2], delete_y + 90)
    rounded_box(draw, approval_box, fill=GREEN_SOFT, outline=GREEN, width=2)
    centered_text(draw, approval_box, "Single-use, revision-bound approval", font_obj=label_font, fill=INK)
    for source_box in (boxes[2], boxes[3]):
        cx = (source_box[0] + source_box[2]) / 2
        arrow(draw, (cx, source_box[3]), (cx, approval_box[1] - 4), color=GREEN)

    deleted_box = (approval_box[0], approval_box[3] + 60, approval_box[2], approval_box[3] + 60 + 90)
    rounded_box(draw, deleted_box, fill=INK, outline=None)
    centered_text(draw, deleted_box, "Deleted from vault\n(not guaranteed secure erasure)", font_obj=label_font, fill=WHITE)
    arrow(draw, ((approval_box[0] + approval_box[2]) / 2, approval_box[3]), ((approval_box[0] + approval_box[2]) / 2, deleted_box[1] - 4))

    caption = "Every path a record can take between private, authorized, and deleted \u2014 there is no path that grants AI access without an explicit action."
    draw.text((80, height - 45), caption, font=caption_font, fill=MUTED)
    save(img, "permission-lifecycle-diagram.png")


def main():
    render_request_flow_diagram()
    render_component_diagram()
    render_permission_lifecycle_diagram()


if __name__ == "__main__":
    main()
