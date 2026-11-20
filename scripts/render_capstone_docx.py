"""Render docs/lumen-capstone-report.md into the official .docx planning template.

This fills in the supplied course template (passed explicitly, never committed to the
repository) with the current report content, preserving the template's own title page,
heading styling, and footer. Run it again any time the Markdown report changes:

    .venv/bin/python scripts/render_capstone_docx.py --template /path/to/template.docx

Markdown support is intentionally narrow: ``## N. Heading`` section headings matching the
template's own section names, ``### Subheading`` within a section, fenced ```text``` blocks,
GitHub-flavored two-column-or-more tables, ``**bold**``/`` `code` `` inline spans,
``![alt](path)`` images (path resolved relative to the Markdown file), and ``N. item``
numbered-list lines (each becomes its own paragraph). The report does not currently use
bullet lists or links, so those are not handled.

Each template section heading paragraph carries the course's own placeholder "Click or tap
here to enter text." content, either as an inline content control nested in the same
paragraph, a separate floating content control immediately after it, or (for the GitHub
section) plain bulleted instruction paragraphs. All of that placeholder content is removed
before the real report content is inserted; see ``clean_template_section``.
"""

import argparse
import copy
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docx.text.paragraph import Paragraph

HEADING_COLOR = RGBColor(0xA6, 0x19, 0x2E)
FONT_NAME = "Open Sans"
BODY_SIZE = Pt(11)
CODE_FONT = "Consolas"
CODE_SIZE = Pt(9)

INLINE_PATTERN = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")


def inline_spans(text: str) -> list[tuple[str, bool, bool]]:
    """Splits text into (text, bold, code) spans from **bold** and `code` markers."""
    spans = []
    for piece in INLINE_PATTERN.split(text):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**"):
            spans.append((piece[2:-2], True, False))
        elif piece.startswith("`") and piece.endswith("`"):
            spans.append((piece[1:-1], False, True))
        else:
            spans.append((piece, False, False))
    return spans


def parse_report(markdown: str) -> tuple[list[str], dict[str, list[dict]]]:
    """Returns (front_matter_lines, {section_title: blocks})."""
    lines = markdown.splitlines()
    heading_re = re.compile(r"^##\s+\d+\.\s+(.+)$")

    front_matter = []
    sections: dict[str, list[dict]] = {}
    current_title = None
    current_lines: list[str] = []

    def flush():
        if current_title is not None:
            sections[current_title] = parse_blocks(current_lines)

    for line in lines:
        match = heading_re.match(line.strip())
        if match:
            flush()
            current_title = match.group(1).strip()
            current_lines = []
            continue
        if line.startswith("# ") or line.startswith("**Module"):
            continue  # Redundant with the template's own title-page boilerplate.
        if current_title is None:
            front_matter.append(line)
        else:
            current_lines.append(line)
    flush()

    while front_matter and not front_matter[0].strip():
        front_matter.pop(0)
    while front_matter and not front_matter[-1].strip():
        front_matter.pop()
    return front_matter, sections


def parse_blocks(lines: list[str]) -> list[dict]:
    blocks: list[dict] = []
    i = 0
    paragraph_buffer: list[str] = []

    def flush_paragraph():
        if paragraph_buffer:
            text = " ".join(paragraph_buffer).strip()
            if text:
                blocks.append({"type": "paragraph", "text": text})
            paragraph_buffer.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            i += 1
            continue
        if stripped.startswith("### "):
            flush_paragraph()
            blocks.append({"type": "subheading", "text": stripped[4:].strip()})
            i += 1
            continue
        image_match = re.match(r"^!\[(.*)\]\((.*)\)$", stripped)
        if image_match:
            flush_paragraph()
            blocks.append({"type": "image", "alt": image_match.group(1), "path": image_match.group(2)})
            i += 1
            continue
        if stripped.startswith("```"):
            flush_paragraph()
            i += 1
            code_lines = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # Skip the closing fence.
            blocks.append({"type": "code", "text": "\n".join(code_lines)})
            continue
        if stripped.startswith("|"):
            flush_paragraph()
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            rows = [
                [cell.strip() for cell in row.strip("|").split("|")]
                for row in table_lines
                if not re.fullmatch(r"\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?", row)
            ]
            blocks.append({"type": "table", "rows": rows})
            continue
        if re.match(r"^\d+\.\s", stripped):
            # A numbered list item: each one is its own paragraph, unlike ordinary
            # wrapped prose, since the source has no blank line between items.
            flush_paragraph()
            blocks.append({"type": "paragraph", "text": stripped})
            i += 1
            continue
        paragraph_buffer.append(stripped)
        i += 1
    flush_paragraph()
    return blocks


def copy_pPr(template_pPr):
    """Copies the template's spacing/font pPr for new body content, but never its
    numPr: that numbering is what makes the template's 10 section headings read as
    "1. Project title" .. "10. Public GitHub repository", and must not continue into
    the plain paragraphs, tables, and subheadings inserted under each heading.
    """
    if template_pPr is None:
        return None
    clone = copy.deepcopy(template_pPr)
    numPr = clone.find(qn("w:numPr"))
    if numPr is not None:
        clone.remove(numPr)
    return clone


def new_body_paragraph(document, template_pPr, spans, *, bold=False, size=BODY_SIZE):
    paragraph = document.add_paragraph()
    pPr = copy_pPr(template_pPr)
    if pPr is not None:
        paragraph._p.insert(0, pPr)
    for text, span_bold, span_code in spans:
        run = paragraph.add_run(text)
        run.font.name = CODE_FONT if span_code else FONT_NAME
        run.font.size = CODE_SIZE if span_code else size
        run.font.bold = bold or span_bold
    return paragraph


def new_code_paragraph(document, template_pPr, code_text):
    paragraph = document.add_paragraph()
    pPr = copy_pPr(template_pPr)
    if pPr is not None:
        paragraph._p.insert(0, pPr)
    lines = code_text.split("\n")
    for index, line in enumerate(lines):
        run = paragraph.add_run(line if line else "\u00a0")
        run.font.name = CODE_FONT
        run.font.size = CODE_SIZE
        if index < len(lines) - 1:
            run.add_break()
    return paragraph


def new_table(document, rows):
    if not rows:
        return None
    table = document.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = document.styles["Table Grid"]
    for row_index, row in enumerate(rows):
        for col_index, cell_text in enumerate(row):
            cell = table.cell(row_index, col_index)
            cell.text = ""
            paragraph = cell.paragraphs[0]
            for run in list(paragraph.runs):
                run._r.getparent().remove(run._r)
            for text, bold, code in inline_spans(cell_text):
                run = paragraph.add_run(text)
                run.font.name = CODE_FONT if code else FONT_NAME
                run.font.size = CODE_SIZE if code else Pt(10)
                run.font.bold = bold or row_index == 0
    return table


def insert_after(anchor_element, new_element):
    anchor_element.addnext(new_element)
    return new_element


def find_ordered_headings(document, titles: set[str]) -> list[tuple[str, Paragraph]]:
    """Locates each target section heading paragraph, in document order."""
    found = []
    seen = set()
    for paragraph in document.paragraphs:
        if not (paragraph.style.name == "Normal (Web)" and paragraph.runs and paragraph.runs[0].bold):
            continue
        text = paragraph.runs[0].text.strip()
        if text in titles and text not in seen:
            found.append((text, paragraph))
            seen.add(text)
    missing = titles - seen
    if missing:
        raise SystemExit(f"These Markdown sections do not match a template heading: {sorted(missing)}")
    return found


def clean_template_section(heading_paragraph, next_heading_paragraph) -> None:
    """Strips the template's own placeholder content for one section.

    This removes: (1) every non-pPr child of the heading paragraph itself, which clears
    both its instructional runs and any inline content-control placeholder nested inside
    it, and (2) every body-level sibling between this heading and the next one (or the
    end of the document), which removes a floating placeholder content control or
    leftover instruction paragraphs that are not nested inside the heading paragraph.
    """
    p = heading_paragraph._p
    for child in list(p):
        if child.tag != qn("w:pPr"):
            p.remove(child)

    end_marker = next_heading_paragraph._p if next_heading_paragraph is not None else None
    node = p.getnext()
    while node is not None and node is not end_marker and node.tag != qn("w:sectPr"):
        following = node.getnext()
        node.getparent().remove(node)
        node = following


def new_image_paragraph(document, path, *, width=None):
    document.add_picture(str(path), width=width or Inches(6.2))
    picture_paragraph = document.paragraphs[-1]
    picture_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    return picture_paragraph


def render_section(document, heading_paragraph, title, blocks, template_pPr, image_base_dir):
    run = heading_paragraph.add_run(title)
    run.font.name = FONT_NAME
    run.font.size = BODY_SIZE
    run.font.bold = True
    run.font.color.rgb = HEADING_COLOR

    anchor = heading_paragraph._p
    for block in blocks:
        if block["type"] == "subheading":
            paragraph = new_body_paragraph(
                document, template_pPr, [(block["text"], True, False)], bold=True
            )
            anchor = insert_after(anchor, paragraph._p)
        elif block["type"] == "code":
            paragraph = new_code_paragraph(document, template_pPr, block["text"])
            anchor = insert_after(anchor, paragraph._p)
        elif block["type"] == "image":
            paragraph = new_image_paragraph(document, image_base_dir / block["path"])
            anchor = insert_after(anchor, paragraph._p)
        elif block["type"] == "table":
            table = new_table(document, block["rows"])
            if table is not None:
                anchor = insert_after(anchor, table._tbl)
        else:
            paragraph = new_body_paragraph(document, template_pPr, inline_spans(block["text"]))
            anchor = insert_after(anchor, paragraph._p)


def remove_editing_restriction(document) -> None:
    """Removes the template's "Restrict Editing: Filling in forms" protection.

    The template locks all normal text so only its own content controls are
    editable, which is appropriate for the fill-in-the-blanks template itself.
    Once rendered, this report has no content controls left (clean_template_section
    removed them), so that protection would otherwise lock the entire document
    with no editable region at all. A final report should be normally editable.
    """
    settings = document.settings.element
    protection = settings.find(qn("w:documentProtection"))
    if protection is not None:
        settings.remove(protection)


def scrub_personal_metadata(document) -> None:
    """Clears the template authors' names and other identifying metadata.

    Copying the template file copies its docProps/core.xml too, including the real
    names of whoever last edited the course template -- not this project's author.
    That must not end up in a published report.
    """
    properties = document.core_properties
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
    # python-docx's last_printed setter does not accept None to clear it; drop the
    # element directly instead.
    lastPrinted = properties._element.find(qn("cp:lastPrinted"))
    if lastPrinted is not None:
        properties._element.remove(lastPrinted)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True, help="Path to the official .docx planning template.")
    parser.add_argument(
        "--source", default="docs/lumen-capstone-report.md", help="Markdown report to render."
    )
    parser.add_argument(
        "--output", default="docs/lumen-capstone-report.docx", help="Where to write the .docx."
    )
    args = parser.parse_args()

    template_path = Path(args.template).expanduser()
    if not template_path.is_file():
        raise SystemExit(f"Template not found: {template_path}")
    source_path = Path(args.source)
    output_path = Path(args.output)

    markdown = source_path.read_text()
    front_matter, sections = parse_report(markdown)

    shutil.copy(template_path, output_path)
    document = Document(output_path)

    ordered_headings = find_ordered_headings(document, set(sections))

    # A representative body-paragraph pPr (spacing/numbering/font) to reuse for new content.
    sample_pPr = None
    for paragraph in document.paragraphs:
        if paragraph.style.name == "Normal (Web)" and paragraph._p.find(qn("w:pPr")) is not None:
            sample_pPr = paragraph._p.find(qn("w:pPr"))
            break

    # Clean every section's placeholder content before inserting anything, using the
    # original document order so each "next heading" boundary is still correct.
    for index, (_, heading_paragraph) in enumerate(ordered_headings):
        next_paragraph = ordered_headings[index + 1][1] if index + 1 < len(ordered_headings) else None
        clean_template_section(heading_paragraph, next_paragraph)

    # Insert front matter (the "Prepared/Revised" note and intro paragraph) right
    # after the template's title-page boilerplate, before the first section heading.
    first_heading_p = ordered_headings[0][1]._p
    anchor = first_heading_p.getprevious()
    for block in parse_blocks(front_matter):
        if block["type"] != "paragraph":
            continue
        paragraph = new_body_paragraph(document, sample_pPr, inline_spans(block["text"]))
        anchor = insert_after(anchor, paragraph._p)

    for title, heading_paragraph in ordered_headings:
        render_section(document, heading_paragraph, title, sections[title], sample_pPr, source_path.parent)

    remove_editing_restriction(document)
    scrub_personal_metadata(document)
    document.save(output_path)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
