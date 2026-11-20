import io
import math
import re
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from docx import Document
from docx.text.paragraph import Paragraph
from lxml.etree import XMLSyntaxError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_UPLOAD = 12 * 1024 * 1024
MAX_TEXT = 600_000
CHUNK_SIZE = 2000


def chunk_text(text: str) -> list[str]:
    raw = text.encode("utf-8")
    chunks = []
    start = 0
    while start < len(raw):
        end = min(start + CHUNK_SIZE, len(raw))
        while end < len(raw) and raw[end] & 0xC0 == 0x80:
            end -= 1
        chunks.append(raw[start:end].decode("utf-8"))
        if end == len(raw):
            break
        start = end - 150
        while raw[start] & 0xC0 == 0x80:
            start += 1
    return chunks


def extract(filename: str, content: bytes) -> list[dict]:
    suffix = Path(filename).suffix.lower()
    if not content or len(content) > MAX_UPLOAD:
        raise ValueError("Choose a nonempty file no larger than 12 MiB.")
    if suffix == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                raise ValueError("Password-protected PDFs are not supported.")
            if len(reader.pages) > 400:
                raise ValueError("PDFs are limited to 400 pages.")
            sections = []
            size = 0
            for number, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                size += len(text)
                if size > MAX_TEXT:
                    raise ValueError("Extracted text exceeds 600,000 characters.")
                sections.append((f"page {number}", text))
        except PdfReadError as exc:
            raise ValueError("This PDF could not be read.") from exc
    elif suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if sum(info.file_size for info in archive.infolist()) > 30 * 1024 * 1024:
                    raise ValueError("Expanded Word file exceeds the 30 MiB safety limit.")
                if "word/document.xml" not in archive.namelist():
                    raise ValueError("Not a valid Word .docx file.")
            doc = Document(io.BytesIO(content))
            paragraphs = []
            for block in doc.iter_inner_content():
                if isinstance(block, Paragraph):
                    paragraphs.append(block.text)
                else:
                    paragraphs.extend(
                        " | ".join(cell.text for cell in row.cells) for row in block.rows
                    )
            sections = [("text", "\n".join(paragraphs))]
        except (zipfile.BadZipFile, KeyError, XMLSyntaxError) as exc:
            raise ValueError("This Word file could not be read.") from exc
    elif suffix in {".txt", ".md"}:
        try:
            sections = [("text", content.decode("utf-8"))]
        except UnicodeDecodeError as exc:
            raise ValueError("Text files must be UTF-8 encoded.") from exc
    else:
        raise ValueError("Supported formats: PDF, Word (.docx), TXT, and Markdown. Not .doc.")
    if sum(len(text) for _, text in sections) > MAX_TEXT:
        raise ValueError("Extracted text exceeds 600,000 characters.")
    chunks = []
    for location, text in sections:
        text = text.replace("\x00", "").strip()
        for chunk in chunk_text(text):
            chunks.append({"location": location, "text": chunk})
    if not chunks:
        raise ValueError("No readable text found. Scanned PDFs need OCR before importing.")
    return chunks


STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "i",
        "me",
        "my",
        "you",
        "your",
        "what",
        "when",
        "where",
        "how",
        "why",
        "can",
        "could",
        "would",
        "should",
        "do",
        "does",
        "did",
        "to",
        "of",
        "for",
        "from",
        "in",
        "on",
        "at",
        "and",
        "or",
        "it",
        "this",
        "that",
        "about",
        "please",
        "tell",
        "know",
        "have",
        "has",
        "with",
        "using",
        "summarize",
        "summary",
    ]
)


def source_chunks(documents: list[dict], notes: list[dict], mails: list[dict] | None = None) -> list[dict]:
    candidates = []
    for document in documents:
        if document["authorized"]:
            for number, chunk in enumerate(document["chunks"], 1):
                candidates.append(
                    {
                        "record_id": document["id"],
                        "kind": "document",
                        "title": document["title"],
                        "location": f"{chunk['location']}, chunk {number}",
                        "text": chunk["text"],
                    }
                )
    for note in notes:
        if note["authorized"]:
            for number, chunk in enumerate(chunk_text(note["body"]), 1):
                candidates.append(
                    {
                        "record_id": note["id"],
                        "kind": "note",
                        "title": note["title"],
                        "location": f"note, chunk {number}",
                        "text": chunk,
                    }
                )
    for mail_message in mails or []:
        if mail_message["authorized"]:
            for number, chunk in enumerate(chunk_text(mail_message["body"]), 1):
                candidates.append(
                    {
                        "record_id": mail_message["id"],
                        "kind": "mail_message",
                        "title": mail_message["subject"],
                        "location": f"email from {mail_message['sender']}, chunk {number}",
                        "text": chunk,
                    }
                )
    return candidates


def retrieve(
    query: str,
    documents: list[dict],
    notes: list[dict],
    mails: list[dict] | None = None,
    limit: int = 8,
) -> list[dict]:
    terms = set(re.findall(r"\w+", query.lower())) - STOP_WORDS
    if not terms:
        return []
    ranked = []
    for source in source_chunks(documents, notes, mails):
        words = set(re.findall(r"\w+", (source["title"] + " " + source["text"]).lower()))
        matches = len(terms & words)
        if matches:
            ranked.append((matches / len(terms), source))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [
        {**source, "citation": f"S{number}"} for number, (_, source) in enumerate(ranked[:limit], 1)
    ]


async def semantic_retrieve(
    query: str,
    documents: list[dict],
    notes: list[dict],
    embed: Callable[[list[str]], Awaitable[list[list[float]]]],
    mails: list[dict] | None = None,
    limit: int = 2,
) -> list[dict]:
    candidates = source_chunks(documents, notes, mails)
    if not candidates:
        return []
    query_vector = (await embed(["search_query: " + query]))[0]
    query_norm = math.hypot(*query_vector)
    ranked = []
    for offset in range(0, len(candidates), 16):
        batch = candidates[offset : offset + 16]
        vectors = await embed(
            ["search_document: " + source["title"] + "\n" + source["text"] for source in batch]
        )
        for source, vector in zip(batch, vectors, strict=True):
            if len(vector) != len(query_vector):
                raise ValueError("Embedding dimensions changed during retrieval. Ask again.")
            norm = math.hypot(*vector)
            score = sum(
                (a / query_norm) * (b / norm)
                for a, b in zip(query_vector, vector, strict=True)
            )
            # A heuristic relevance floor, not a probability that the source supports the answer.
            if score >= 0.5:
                ranked.append((score, source))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [
        {**source, "citation": f"S{number}", "score": round(score, 4)}
        for number, (score, source) in enumerate(ranked[:limit], 1)
    ]
