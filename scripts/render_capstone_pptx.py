"""Builds docs/lumen-capstone-presentation.pptx: a 10-minute capstone deck following the
official 7-part structure (opening/overview, why it matters, architecture, key design
decisions, evaluation and results, repository, closing reflection).

Content is sourced from docs/lumen-capstone-report.md and docs/lumen-presentation-plan.md;
nothing here claims a result beyond what those documents already establish. Run:

    .venv/bin/python scripts/render_capstone_pptx.py

Slide content lives in SLIDES below, separate from the rendering helpers, so the deck can
be revised by editing data rather than layout code.
"""

from datetime import UTC, datetime
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_AUTO_SIZE, MSO_VERTICAL_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

# Lumen's actual brand palette and wordmark, taken from lumen/static/style.css
# (--green, --gold, --ink, --muted, --bg, --green-soft) and the .brand-mark element,
# rather than a borrowed template color, so the deck looks like the real product.
GREEN = RGBColor(0x2D, 0x5C, 0x48)
GOLD = RGBColor(0xB3, 0x94, 0x61)
INK = RGBColor(0x25, 0x36, 0x2F)
MUTED = RGBColor(0x5B, 0x66, 0x60)
BG_LIGHT = RGBColor(0xF7, 0xF8, 0xFA)
GREEN_SOFT = RGBColor(0xEA, 0xF1, 0xED)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
FONT = "Open Sans"
LOGO_FONT = "Georgia"

SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)
MARGIN = Inches(0.6)

TITLE = {
    "headline": "Lumen",
    "subtitle": "A Local-First, Permission-Aware Personal AI Assistant",
    "footer": "Final Capstone Presentation \u00b7 Module 7",
}

SLIDES = [
    {
        "kind": "bullets",
        "kicker": "1. Opening and project overview",
        "title": "The problem, the user, the goal",
        "bullets": [
            "Personal information is scattered across documents, notes, and messages \u2014 finding a deadline or preparing a reply means repeated searching and copying between apps.",
            "A general-purpose model doesn't know these personal facts unless the user supplies evidence, and a fluent answer can conceal what's actually missing or unsupported.",
            "Intended user: an individual on a Mac who wants real assistance without automatically uploading a personal library to a hosted model.",
            "Goal: a single-user assistant that answers from authorized material, summarizes documents, drafts messages, and supports lightweight organization \u2014 with an inspectable answer and honored revocation/approval rules.",
        ],
        "notes": "Open with the gap: fluent general models don't know your personal facts, and don't tell you what they're missing. Introduce the target user explicitly \u2014 a Mac user who wants help without a wholesale upload of their library. State the goal in terms of successful behavior (evidence, inspectability, honored rules), not just features.",
    },
    {
        "kind": "bullets",
        "kicker": "2. Why this problem matters",
        "title": "Why this needs an agent, not just a chatbot",
        "bullets": [
            "A plain chat window over a local model has no memory, no permission model, and no record of what evidence an answer came from \u2014 real information work needs more than fluent text.",
            "An agent-based approach fits because the task is bounded and evidence-based: retrieve the right permitted material, ground the answer in it, and act only through explicit, reviewable steps.",
            "The real risk of agent-style systems is scope creep into autonomy nobody asked for. Lumen's answer: every consequential action sits behind an explicit approval, never behind model judgment alone.",
        ],
        "notes": "This slide justifies the architecture choice itself. Emphasize the trade-off explicitly: more structure and friction, in exchange for control and inspectability, is a deliberate design stance, not a limitation to apologize for.",
    },
    {
        "kind": "image",
        "kicker": "3. System architecture",
        "title": "A deterministic controller, not a free-running agent",
        "image": "architecture-diagram.png",
        "caption": "Task-specific local model calls under one application controller \u2014 not a free-running planning loop or three cooperating agents.",
        "notes": "Walk the top path top to bottom: every request passes permission checks before it ever reaches the model, and the result is checked again before being returned. Point out the two gold 'separately' branches are optional and always user-triggered, never automatic.",
    },
    {
        "kind": "table",
        "kicker": "3. System architecture",
        "title": "Major components and responsibilities",
        "headers": ["Component", "Responsibility"],
        "rows": [
            ["Controller and API", "Sessions, permissions, model-work admission, approvals, workflows"],
            ["Encrypted storage", "SQLite with AES-256-GCM, Scrypt-derived key held only while unlocked"],
            ["Document processing", "Extraction, chunking, keyword/semantic retrieval"],
            ["Inference", "Loopback-only Ollama calls, model metadata checks, context limits"],
            ["Public research", "Fixed Brave Search destination, bounded snippet results"],
            ["Mail import", "Read-only IMAP fetch, HTML-to-text extraction, candidate-reminder validation"],
            ["Evaluation tooling", "18-case synthetic dataset, local runner, human-scoring rubric"],
            ["Native experience", "Menu bar, explicit sharing, on-device dictation (Swift/AppKit)"],
        ],
        "notes": "This table is the map for the rest of the talk: each design decision and each piece of evaluation evidence traces back to one of these rows.",
    },
    {
        "kind": "bullets",
        "kicker": "4. Key design decisions",
        "title": "Memory and retrieval",
        "bullets": [
            "Memory is explicit and encrypted: notes and preferences enter the model's context only when the user authorizes them \u2014 no hidden automatic extraction.",
            "Retrieval defaults to local keyword overlap; optional semantic retrieval (local embeddings, cosine similarity, 0.5 floor) addresses vocabulary mismatch without a hosted embedding service or a plaintext vector index.",
            "Revoking access excludes a record from retrieval immediately, including mid-request \u2014 permission state is checked, not just read once at the start.",
        ],
        "notes": "This is the first of three 'key design decisions' slides. Keep the thread: every decision here trades convenience for an explicit, inspectable boundary.",
    },
    {
        "kind": "bullets",
        "kicker": "4. Key design decisions",
        "title": "Reasoning structure and coordination",
        "bullets": [
            "Rejected Tree-of-Thought: the bottleneck is evidence retrieval and faithful communication, not exploring a branching plan \u2014 extra reasoning branches add local computation without better grounding.",
            "A future Evidence/Response/Review multi-agent design is documented but deliberately not implemented \u2014 it must demonstrate a quality benefit over the current baseline first. Agents sharing one model can also share its errors.",
            "Later additions (evaluation harness, UI consolidation, Gmail import) extended capability without adding autonomy \u2014 the same permission philosophy applied to a new data source instead of a new one being invented.",
        ],
        "notes": "This slide is where to be explicit that 'not building X' was itself a design decision, with a reason, not an omission.",
    },
    {
        "kind": "bullets",
        "kicker": "4. Key design decisions",
        "title": "Guardrails",
        "bullets": [
            "Every external or consequential action requires a single-use, revision-bound, expiring approval \u2014 deletion, Brave search, and mail-derived reminders all go through the same mechanism.",
            "No cloud fallback: inference only calls loopback Ollama. A compromised local Ollama install is the trust boundary \u2014 not a silent cloud substitute.",
            "Mail import is read-only \u2014 there is no SMTP capability anywhere in the codebase \u2014 and only runs on an explicit click, never a background schedule.",
        ],
        "notes": "Guardrails slide: tie back to the architecture diagram's checkpoints. These aren't separate bolt-on features \u2014 they're the same controller pattern reused everywhere.",
    },
    {
        "kind": "bullets",
        "kicker": "5. Evaluation and results",
        "title": "What's actually tested",
        "bullets": [
            "165 tests passed, 2 skipped (full suite, including opt-in browser checks) \u2014 authorization/session handling, summary lifecycle, research-and-deletion ordering, sharing/readiness, storage/error handling, and mail import.",
            "Mail import specifically: IMAP response parsing, message-ID deduplication, a 200-message batch cap, credential-echo-free error handling, and candidate-reminder validation \u2014 all against a fake IMAP double, no real network access.",
            "This demonstrates deterministic application behavior under synthetic conditions \u2014 it is not a measurement of model accuracy.",
        ],
        "notes": "Be precise about what 165/2 actually proves: permission and lifecycle correctness, not answer quality. The next slide handles answer quality honestly.",
    },
    {
        "kind": "bullets",
        "kicker": "5. Evaluation and results",
        "title": "Model quality: honest status",
        "bullets": [
            "Retrieval checkpoint example: semantic retrieval found a paraphrased fact (a household guide's USD 47/month saving) that keyword search missed; revoking access removed it from the next answer.",
            "A synthetic, scored evaluation harness now exists \u2014 18 cases, a human-scoring rubric, timing/call reports \u2014 but no live, human-scored baseline has been run against a real model yet.",
            "Proposed targets (90% answer correctness, 95% supported personal-fact claims, 90% appropriate abstention) are evaluation goals, not achieved results.",
        ],
        "notes": "This is the slide most likely to get a tough question. Don't soften it: the harness is real infrastructure, the quality numbers are not yet measured. Say so plainly.",
    },
    {
        "kind": "bullets",
        "kicker": "6. Repository and implementation",
        "title": "What's in the repository",
        "bullets": [
            "Public repository URL: github.com/rajitnikhare/lumen \u2014 created and reachable; not yet populated as of this revision, with the push still pending.",
            "README covering the project, architecture, setup, and day-to-day usage; full application and native source; the complete test suite, including the mail-import fakes.",
            "Synthetic evaluation dataset and human-scoring rubric; design documents (architecture, safety/intervention plan, UI experience plan) distinguishing implemented from proposed work.",
            "Reproduce locally: install dependencies, start Ollama with a local model, run `lumen`. No personal vault is required for the automated tests.",
        ],
        "notes": "If the URL is live by presentation time, show it briefly on screen. If not, say explicitly that it's pending and point to the local reproduction steps instead.",
    },
    {
        "kind": "bullets",
        "kicker": "7. Closing reflection",
        "title": "What I'd tell myself at the start",
        "bullets": [
            "Main takeaway: dependable, inspectable assistance at an acceptable local cost \u2014 not maximum autonomy \u2014 was the actual success criterion, and it shaped every later decision.",
            "What worked well: the explicit permission model held up as scope grew \u2014 Gmail import reused the same approval philosophy instead of inventing a new one. Writing deterministic tests surfaced real lifecycle bugs (seven found and fixed) that a \u201cdoes it answer\u201d check would have missed.",
            "What I'd improve next: run the evaluation harness against a real model with human scoring, instead of only validating the harness itself with synthetic responses; verify native sharing and mail import against real hardware and a real account, not only fakes and doubles.",
        ],
        "notes": "Close on the honest ledger: a real, working permission model, proven by tests \u2014 and a clearly named list of what's still unverified. That contrast is the actual thesis of the project.",
    },
]


def set_background(slide, color):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_textbox(slide, left, top, width, height):
    box = slide.shapes.add_textbox(left, top, width, height)
    box.text_frame.word_wrap = True
    return box


def style_run(run, *, size, color=INK, bold=False, font=FONT, italic=False):
    run.font.size = size
    run.font.color.rgb = color
    run.font.bold = bold
    run.font.italic = italic
    run.font.name = font


def add_logo_mark(slide, left, top, size, *, font_size=None):
    """Draws Lumen's actual wordmark: a rounded green square with a serif "L",
    matching the .brand-mark element in lumen/static/style.css exactly, since the
    project has no separate logo image file.
    """
    mark = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, size, size)
    mark.adjustments[0] = 0.32
    mark.fill.solid()
    mark.fill.fore_color.rgb = GREEN
    mark.line.fill.background()
    mark.shadow.inherit = False
    frame = mark.text_frame
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    paragraph = frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.CENTER
    run = paragraph.add_run()
    run.text = "L"
    box_points = size / 914400 * 72
    style_run(run, size=font_size or Pt(box_points * 0.66), color=WHITE, bold=True, font=LOGO_FONT)
    return mark


def add_kicker_and_title(slide, kicker, title):
    kicker_box = add_textbox(slide, MARGIN, Inches(0.45), SLIDE_WIDTH - Inches(1.8), Inches(0.4))
    run = kicker_box.text_frame.paragraphs[0].add_run()
    run.text = kicker.upper()
    style_run(run, size=Pt(14), color=GREEN, bold=True)
    kicker_box.text_frame.paragraphs[0].space_after = Pt(0)

    title_box = add_textbox(slide, MARGIN, Inches(0.85), SLIDE_WIDTH - Inches(1.8), Inches(0.9))
    run = title_box.text_frame.paragraphs[0].add_run()
    run.text = title
    style_run(run, size=Pt(30), color=INK, bold=True)

    add_logo_mark(slide, SLIDE_WIDTH - MARGIN - Inches(0.55), Inches(0.5), Inches(0.55), font_size=Pt(22))

    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, MARGIN, Inches(1.75), SLIDE_WIDTH - 2 * MARGIN, Pt(2.5))
    rule.fill.solid()
    rule.fill.fore_color.rgb = GREEN
    rule.line.fill.background()
    rule.shadow.inherit = False
    return Inches(2.05)


def add_title_slide(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_background(slide, BG_LIGHT)

    add_logo_mark(slide, Inches(6.07), Inches(1.5), Inches(1.2), font_size=Pt(50))

    eyebrow_box = add_textbox(slide, Inches(1), Inches(3.0), SLIDE_WIDTH - Inches(2), Inches(0.4))
    run = eyebrow_box.text_frame.paragraphs[0].add_run()
    run.text = "A LOCAL-FIRST PERSONAL AI ASSISTANT"
    style_run(run, size=Pt(15), color=GOLD, bold=True)
    eyebrow_box.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER

    headline_box = add_textbox(slide, Inches(1), Inches(3.45), SLIDE_WIDTH - Inches(2), Inches(1.1))
    run = headline_box.text_frame.paragraphs[0].add_run()
    run.text = TITLE["headline"]
    style_run(run, size=Pt(60), color=GREEN, bold=True)
    headline_box.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER

    subtitle_box = add_textbox(slide, Inches(1), Inches(4.55), SLIDE_WIDTH - Inches(2), Inches(0.6))
    run = subtitle_box.text_frame.paragraphs[0].add_run()
    run.text = TITLE["subtitle"]
    style_run(run, size=Pt(22), color=INK)
    subtitle_box.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER

    footer_box = add_textbox(slide, Inches(1), Inches(6.6), SLIDE_WIDTH - Inches(2), Inches(0.5))
    run = footer_box.text_frame.paragraphs[0].add_run()
    run.text = TITLE["footer"]
    style_run(run, size=Pt(14), color=MUTED)
    footer_box.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
    return slide


def add_bullets_slide(prs, spec):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_background(slide, WHITE)
    top = add_kicker_and_title(slide, spec["kicker"], spec["title"])

    body = add_textbox(slide, MARGIN, top + Inches(0.15), SLIDE_WIDTH - 2 * MARGIN, Inches(4.5))
    frame = body.text_frame
    frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    for index, bullet in enumerate(spec["bullets"]):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.space_after = Pt(18)
        bullet_run = paragraph.add_run()
        bullet_run.text = "\u2726  "
        style_run(bullet_run, size=Pt(20), color=GOLD, bold=True)
        text_run = paragraph.add_run()
        text_run.text = bullet
        style_run(text_run, size=Pt(20), color=INK)
    return slide


def add_table_slide(prs, spec):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_background(slide, WHITE)
    top = add_kicker_and_title(slide, spec["kicker"], spec["title"])

    rows = len(spec["rows"]) + 1
    cols = len(spec["headers"])
    table_width = SLIDE_WIDTH - 2 * MARGIN
    table_height = Inches(4.6)
    graphic_frame = slide.shapes.add_table(rows, cols, MARGIN, top + Inches(0.1), table_width, table_height)
    table = graphic_frame.table
    table.columns[0].width = Emu(int(table_width * 0.28))
    table.columns[1].width = Emu(int(table_width * 0.72))

    for col, heading in enumerate(spec["headers"]):
        cell = table.cell(0, col)
        cell.fill.solid()
        cell.fill.fore_color.rgb = GREEN
        cell.text_frame.paragraphs[0].text = ""
        run = cell.text_frame.paragraphs[0].add_run()
        run.text = heading
        style_run(run, size=Pt(15), color=WHITE, bold=True)
        cell.vertical_anchor = MSO_VERTICAL_ANCHOR.MIDDLE

    for row_index, row in enumerate(spec["rows"], start=1):
        for col_index, value in enumerate(row):
            cell = table.cell(row_index, col_index)
            cell.fill.solid()
            cell.fill.fore_color.rgb = GREEN_SOFT if row_index % 2 else WHITE
            run = cell.text_frame.paragraphs[0].add_run()
            run.text = value
            style_run(run, size=Pt(13), color=INK, bold=(col_index == 0))
            cell.vertical_anchor = MSO_VERTICAL_ANCHOR.MIDDLE
    return slide


def add_image_slide(prs, spec):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_background(slide, WHITE)
    top = add_kicker_and_title(slide, spec["kicker"], spec["title"])

    image_path = Path("docs") / spec["image"]
    with Image.open(image_path) as source:
        aspect = source.height / source.width
    picture_width = SLIDE_WIDTH - 2 * MARGIN
    picture_height = Emu(int(picture_width * aspect))
    max_height = Inches(4.5)
    if picture_height > max_height:
        picture_height = max_height
        picture_width = Emu(int(picture_height / aspect))
    left = (SLIDE_WIDTH - picture_width) / 2
    slide.shapes.add_picture(str(image_path), left, top + Inches(0.1), width=picture_width, height=picture_height)

    caption = add_textbox(slide, MARGIN, top + Inches(0.1) + picture_height + Inches(0.15), SLIDE_WIDTH - 2 * MARGIN, Inches(0.6))
    run = caption.text_frame.paragraphs[0].add_run()
    run.text = spec["caption"]
    style_run(run, size=Pt(16), color=MUTED, italic=True)
    return slide


def add_notes(slide, text):
    if text:
        slide.notes_slide.notes_text_frame.text = text


def add_page_footer(slide, prs, page_number):
    footer = add_textbox(slide, MARGIN, SLIDE_HEIGHT - Inches(0.5), SLIDE_WIDTH - 2 * MARGIN, Inches(0.35))
    paragraph = footer.text_frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.RIGHT
    run = paragraph.add_run()
    run.text = f"Lumen \u00b7 Capstone \u00b7 {page_number}"
    style_run(run, size=Pt(11), color=MUTED)


def scrub_personal_metadata(prs) -> None:
    """Clears python-pptx's own baked-in default template metadata (its author's
    name from the library's internal starter .pptx), not this project's author.
    """
    properties = prs.core_properties
    properties.author = ""
    properties.last_modified_by = ""
    properties.comments = ""
    properties.subject = ""
    properties.keywords = ""
    properties.category = ""
    properties.content_status = ""
    properties.revision = 1
    now = datetime.now(UTC)
    properties.created = now
    properties.modified = now


def main():
    prs = Presentation()
    prs.slide_width = SLIDE_WIDTH
    prs.slide_height = SLIDE_HEIGHT

    add_title_slide(prs)

    for page_number, spec in enumerate(SLIDES, start=2):
        if spec["kind"] == "bullets":
            slide = add_bullets_slide(prs, spec)
        elif spec["kind"] == "table":
            slide = add_table_slide(prs, spec)
        elif spec["kind"] == "image":
            slide = add_image_slide(prs, spec)
        else:
            raise ValueError(f"Unknown slide kind: {spec['kind']}")
        add_page_footer(slide, prs, page_number)
        add_notes(slide, spec.get("notes"))

    scrub_personal_metadata(prs)
    output_path = Path("docs/lumen-capstone-presentation.pptx")
    prs.save(output_path)
    print(f"Wrote {output_path} ({len(prs.slides)} slides)")


if __name__ == "__main__":
    main()
