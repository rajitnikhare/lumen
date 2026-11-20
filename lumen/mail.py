import email
import email.message
import imaplib
import json
import re
from contextlib import suppress
from datetime import UTC, datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

IMAP_HOST_DEFAULT = "imap.gmail.com"
IMAP_PORT_DEFAULT = 993
MAX_MESSAGES_PER_CHECK = 200
MAX_BODY_CHARS = 20_000


class MailError(Exception):
    pass


class _TextExtractor(HTMLParser):
    """Strips HTML markup for display text. Never fetches remote images or renders markup."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    with suppress(Exception):
        parser.feed(html)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(parser.parts)).strip()


def _decode_header_value(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        parts = decode_header(raw)
    except (ValueError, LookupError):
        return ""
    decoded = "".join(
        chunk.decode(encoding or "utf-8", errors="replace") if isinstance(chunk, bytes) else chunk
        for chunk, encoding in parts
    )
    # Read-only display text: strip control characters rather than re-emit raw header bytes.
    return "".join(character for character in decoded if character.isprintable() or character == " ").strip()


def _plain_text_body(message: email.message.Message) -> tuple[str, bool]:
    plain: bytes | None = None
    plain_charset = "utf-8"
    html: bytes | None = None
    html_charset = "utf-8"
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type()
            if content_type == "text/plain" and plain is None:
                plain = part.get_payload(decode=True)
                plain_charset = part.get_content_charset() or "utf-8"
            elif content_type == "text/html" and html is None:
                html = part.get_payload(decode=True)
                html_charset = part.get_content_charset() or "utf-8"
    else:
        content_type = message.get_content_type()
        payload = message.get_payload(decode=True)
        if content_type == "text/plain":
            plain, plain_charset = payload, message.get_content_charset() or "utf-8"
        elif content_type == "text/html":
            html, html_charset = payload, message.get_content_charset() or "utf-8"
    if plain:
        text = plain.decode(plain_charset, errors="replace")
    elif html:
        text = html_to_text(html.decode(html_charset, errors="replace"))
    else:
        return "", False
    text = text.replace("\x00", "").strip()
    if len(text) > MAX_BODY_CHARS:
        return text[:MAX_BODY_CHARS], True
    return text, False


def _connect(host: str, port: int, username: str, app_password: str) -> imaplib.IMAP4_SSL:
    try:
        connection = imaplib.IMAP4_SSL(host, port, timeout=30)
    except (OSError, imaplib.IMAP4.error) as exc:
        raise MailError(
            f"Could not reach {host}:{port}. Check the host/port and your network connection."
        ) from exc
    try:
        connection.login(username, app_password)
    except imaplib.IMAP4.error as exc:
        with suppress(Exception):
            connection.logout()
        # Never echo the server's raw error text: some IMAP servers include the
        # attempted credentials in their failure responses.
        raise MailError(
            "Sign-in failed. Check the email address and app password, and confirm IMAP "
            "access is enabled for this account."
        ) from exc
    return connection


def test_connection(host: str, port: int, username: str, app_password: str) -> None:
    """Verifies read-only IMAP access without importing anything. Raises MailError on failure."""
    connection = _connect(host, port, username, app_password)
    try:
        status, _ = connection.select("INBOX", readonly=True)
        if status != "OK":
            raise MailError("Could not open the inbox folder in read-only mode.")
    finally:
        with suppress(Exception):
            connection.logout()


def fetch_inbox(
    host: str,
    port: int,
    username: str,
    app_password: str,
    since: datetime,
    known_message_ids: set[str],
) -> list[dict]:
    """Read-only IMAP fetch of recent inbox messages not already in ``known_message_ids``.

    Never marks messages as read (``BODY.PEEK``) and never sends anything. Bounded to the
    most recent ``MAX_MESSAGES_PER_CHECK`` messages matching the date window per call.
    """
    connection = _connect(host, port, username, app_password)
    try:
        status, _ = connection.select("INBOX", readonly=True)
        if status != "OK":
            raise MailError("Could not open the inbox folder in read-only mode.")
        date_token = since.strftime("%d-%b-%Y")
        try:
            status, data = connection.uid("search", None, f"(SINCE {date_token})")
        except imaplib.IMAP4.error as exc:
            raise MailError("The mail server rejected the search request.") from exc
        if status != "OK":
            raise MailError("The mail server rejected the search request.")
        uids = data[0].split() if data and data[0] else []
        uids = uids[-MAX_MESSAGES_PER_CHECK:]
        if not uids:
            return []
        try:
            # One batched FETCH for the whole window, not one round trip per message.
            status, body_data = connection.uid("fetch", b",".join(uids), "(BODY.PEEK[])")
        except imaplib.IMAP4.error as exc:
            raise MailError("The mail server rejected the message fetch request.") from exc
        if status != "OK":
            raise MailError("The mail server rejected the message fetch request.")
        messages = []
        for item in body_data:
            if not isinstance(item, tuple) or len(item) != 2:
                continue
            try:
                parsed = email.message_from_bytes(item[1])
            except Exception:  # noqa: BLE001 - a single malformed message must not fail the batch
                continue
            message_id = _decode_header_value(parsed.get("Message-ID"))
            if not message_id or message_id in known_message_ids:
                continue
            subject = _decode_header_value(parsed.get("Subject")) or "(no subject)"
            sender = _decode_header_value(parsed.get("From"))
            try:
                received_at = parsedate_to_datetime(parsed.get("Date", ""))
                if received_at.tzinfo is None:
                    received_at = received_at.replace(tzinfo=UTC)
            except (TypeError, ValueError):
                received_at = datetime.now(UTC)
            body, truncated = _plain_text_body(parsed)
            if not body:
                continue
            messages.append(
                {
                    "message_id": message_id,
                    "subject": subject[:500],
                    "sender": sender[:320],
                    "received_at": received_at.astimezone(UTC).isoformat(),
                    "body": body,
                    "truncated": truncated,
                }
            )
        messages.sort(key=lambda item: item["received_at"])
        return messages
    finally:
        with suppress(Exception):
            connection.logout()


def parse_candidate_reminders(raw: str, batch: list[dict]) -> tuple[list[dict], int]:
    """Validates the model's extraction output against the actual batch.

    Returns ``(candidates, skipped_count)``. Entries referencing a message not in this
    batch, missing a timezone-aware date, or otherwise malformed are dropped rather than
    failing the whole batch: this is a best-effort suggestion, not a factual citation.
    """
    citation_to_message = {f"M{index + 1}": item["message_id"] for index, item in enumerate(batch)}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return [], 0
    if not isinstance(parsed, list):
        return [], 0
    candidates = []
    skipped = 0
    for entry in parsed:
        if not isinstance(entry, dict):
            skipped += 1
            continue
        citation = entry.get("message_citation")
        title = entry.get("title")
        due_at_raw = entry.get("due_at")
        details = entry.get("details", "")
        if (
            not isinstance(citation, str)
            or citation not in citation_to_message
            or not isinstance(title, str)
            or not title.strip()
            or not isinstance(due_at_raw, str)
        ):
            skipped += 1
            continue
        try:
            due_at = datetime.fromisoformat(due_at_raw.replace("Z", "+00:00"))
        except ValueError:
            skipped += 1
            continue
        if due_at.tzinfo is None:
            skipped += 1
            continue
        candidates.append(
            {
                "title": title.strip()[:200],
                "due_at": due_at.astimezone(UTC).isoformat(),
                "details": (details if isinstance(details, str) else "")[:4000],
                "source_message_id": citation_to_message[citation],
            }
        )
    return candidates, skipped
