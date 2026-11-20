import asyncio
import io
import zipfile

import pytest
from docx import Document
from pypdf import PdfWriter

from lumen.documents import CHUNK_SIZE, chunk_text, extract, retrieve, semantic_retrieve


def test_word_paragraphs_and_tables():
    document = Document()
    document.add_paragraph("The project deadline is October 20.")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Milestone"
    table.cell(0, 1).text = "Final presentation"
    document.add_paragraph("After the table.")
    buffer = io.BytesIO()
    document.save(buffer)
    text = "\n".join(chunk["text"] for chunk in extract("plan.docx", buffer.getvalue()))
    assert "October 20" in text
    assert "Milestone | Final presentation" in text
    assert text.index("Milestone") < text.index("After the table")


def test_malformed_word_xml_fails_explicitly():
    source = io.BytesIO()
    Document().save(source)
    malformed = io.BytesIO()
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(malformed, "w") as output:
        for info in original.infolist():
            output.writestr(
                info.filename,
                b"<invalid"
                if info.filename == "word/document.xml"
                else original.read(info.filename),
            )
    with pytest.raises(ValueError, match="could not be read"):
        extract("malformed.docx", malformed.getvalue())


def text_pdf(text: str) -> bytes:
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(content)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_pdf_extracts_page_reference():
    result = extract("schedule.pdf", text_pdf("Meeting at noon on Friday."))
    assert result[0]["location"] == "page 1"
    assert "Meeting at noon" in result[0]["text"]


@pytest.mark.parametrize(
    "filename, content",
    [
        ("old.doc", b"content"),
        ("bad.pdf", b"not a PDF"),
        ("bad.docx", b"invalid zip"),
        ("empty.txt", b""),
        ("wrong.txt", b"\xff"),
    ],
)
def test_invalid_documents_fail_explicitly(filename, content):
    with pytest.raises(ValueError):
        extract(filename, content)


def test_blank_pdf_requests_ocr():
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(ValueError, match="OCR"):
        extract("scan.pdf", buffer.getvalue())


def test_zip_expansion_limit():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "x" * (31 * 1024 * 1024))
    with pytest.raises(ValueError, match="30 MiB"):
        extract("oversized.docx", buffer.getvalue())


def test_unicode_chunks_preserve_characters_and_fit_byte_budget():
    text = "".join(f"{index}A\u00e9\u6f22\U0001f33f" for index in range(2000))
    chunks = chunk_text(text)
    assert len(chunks) > 1
    assert all(len(chunk.encode("utf-8")) <= CHUNK_SIZE for chunk in chunks)
    assert chunks[0] == text[: len(chunks[0])]
    offset = len(chunks[0])
    for chunk in chunks[1:]:
        position = text.find(chunk, max(0, offset - 150))
        assert position >= 0
        assert position <= offset
        offset = position + len(chunk)
    assert offset == len(text)


def test_retrieval_excludes_unauthorized_and_irrelevant_items():
    documents = [
        {
            "id": "allowed",
            "title": "Trip",
            "authorized": True,
            "chunks": [{"text": "The train to Paris leaves at noon.", "location": "page 2"}],
        },
        {
            "id": "denied",
            "title": "Private",
            "authorized": False,
            "chunks": [{"text": "Paris secret booking number", "location": "page 1"}],
        },
    ]
    notes = [
        {
            "id": "allowed-note",
            "title": "Paris packing",
            "body": "Bring an umbrella.",
            "authorized": True,
        },
        {"id": "denied-note", "title": "Paris", "body": "private plans", "authorized": False},
    ]
    results = retrieve("When is the Paris train?", documents, notes)
    assert results[0]["record_id"] == "allowed"
    assert {item["record_id"] for item in results} == {"allowed", "allowed-note"}
    assert results[0]["citation"] == "S1"
    assert retrieve("penguin migration", documents, notes) == []


def test_semantic_retrieval_ranks_limits_and_filters_before_embedding():
    documents = [
        {
            "id": "guide",
            "title": "Household guide",
            "authorized": True,
            "chunks": [
                {"location": "text", "text": text}
                for text in ("memberships", "utilities", "transport", "unrelated")
            ],
        },
        {
            "id": "private",
            "title": "Secret",
            "authorized": False,
            "chunks": [{"location": "text", "text": "private account"}],
        },
    ]
    embedded = []

    async def embed(texts):
        embedded.extend(texts)
        vectors = {
            "memberships": [1.0, 0.0],
            "utilities": [0.9, 0.1],
            "transport": [0.8, 0.2],
        }
        return [
            [1.0, 0.0] if text.startswith("search_query:") else
            vectors.get(text.split("\n")[-1], [0.0, 1.0])
            for text in texts
        ]

    assert retrieve("How can I lower my bills?", documents, []) == []
    sources = asyncio.run(semantic_retrieve("How can I lower my bills?", documents, [], embed))
    assert [source["text"] for source in sources] == ["memberships", "utilities"]
    assert [source["citation"] for source in sources] == ["S1", "S2"]
    assert "private account" not in str(embedded)
    assert sources[0]["score"] == 1.0


def test_semantic_retrieval_empty_library_and_bounded_batches():
    calls = []

    async def embed(texts):
        calls.append(texts)
        return [[1.0, 0.0] for _ in texts]

    assert asyncio.run(semantic_retrieve("bills", [], [], embed)) == []
    assert calls == []
    notes = [
        {"id": str(index), "title": "Note", "body": "text", "authorized": True}
        for index in range(18)
    ]
    assert len(asyncio.run(semantic_retrieve("bills", [], notes, embed))) == 2
    assert [len(batch) for batch in calls] == [1, 16, 2]
