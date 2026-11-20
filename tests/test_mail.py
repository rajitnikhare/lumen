import imaplib
from datetime import UTC, datetime
from email.message import EmailMessage

import pytest

from lumen import mail


class FakeIMAP:
    """A minimal stand-in for imaplib.IMAP4_SSL; no real network is used."""

    def __init__(self, uids_to_raw, valid_password="correct-app-password"):
        self._uids_to_raw = uids_to_raw
        self._valid_password = valid_password
        self.logged_out = False
        self.fetch_calls = 0

    def login(self, username, password):
        if password != self._valid_password:
            raise imaplib.IMAP4.error(f"AUTHENTICATIONFAILED invalid credentials for {username}")
        return "OK", [b"Logged in"]

    def select(self, mailbox, readonly=False):
        assert mailbox == "INBOX"
        assert readonly is True
        return "OK", [b"1"]

    def uid(self, command, *args):
        if command == "search":
            uids = sorted(self._uids_to_raw.keys(), key=int)
            if uids:
                return "OK", [b" ".join(str(uid).encode() for uid in uids)]
            return "OK", [b""]
        if command == "fetch":
            self.fetch_calls += 1
            requested = {int(value) for value in args[0].split(b",")}
            data = []
            for uid in sorted(requested):
                raw = self._uids_to_raw.get(uid)
                if raw is None:
                    continue
                data.append((f"{uid} (UID {uid} BODY[] {{{len(raw)}}}".encode(), raw))
                data.append(b")")
            return "OK", data
        raise AssertionError(f"Unexpected IMAP command: {command}")

    def logout(self):
        self.logged_out = True


def install_fake(monkeypatch, fake):
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", lambda host, port, timeout=30: fake)


def plain_message(subject="Project review", sender="advisor@example.test", body="Please reply.", message_id="<a@example.test>"):
    message = EmailMessage()
    message["Message-ID"] = message_id
    message["Subject"] = subject
    message["From"] = sender
    message["Date"] = "Mon, 01 Dec 2026 09:00:00 +0000"
    message.set_content(body)
    return message.as_bytes()


def test_fetch_inbox_parses_plain_text_and_dedupes(monkeypatch):
    raw = plain_message(body="Project Cedar is due December 12, 2026 at 5pm.")
    fake = FakeIMAP({1: raw})
    install_fake(monkeypatch, fake)
    since = datetime(2026, 1, 1, tzinfo=UTC)

    messages = mail.fetch_inbox("imap.gmail.com", 993, "me@example.test", "correct-app-password", since, set())
    assert len(messages) == 1
    assert messages[0]["message_id"] == "<a@example.test>"
    assert messages[0]["subject"] == "Project review"
    assert "Project Cedar is due December 12" in messages[0]["body"]
    assert fake.logged_out is True

    # Re-fetching with the message_id already known yields nothing new.
    fake2 = FakeIMAP({1: raw})
    install_fake(monkeypatch, fake2)
    messages_again = mail.fetch_inbox(
        "imap.gmail.com", 993, "me@example.test", "correct-app-password", since, {"<a@example.test>"}
    )
    assert messages_again == []


def test_fetch_inbox_falls_back_to_html_to_text_without_executing_scripts(monkeypatch):
    message = EmailMessage()
    message["Message-ID"] = "<html@example.test>"
    message["Subject"] = "Appointment"
    message["From"] = "clinic@example.test"
    message["Date"] = "Tue, 02 Dec 2026 10:00:00 +0000"
    message.set_content(
        "<html><body><script>window.exfiltrate()</script>"
        "<style>.x{color:red}</style>"
        "<p>Your appointment is on Dec 20, 2026.</p></body></html>",
        subtype="html",
    )
    fake = FakeIMAP({1: message.as_bytes()})
    install_fake(monkeypatch, fake)

    messages = mail.fetch_inbox(
        "imap.gmail.com", 993, "me@example.test", "correct-app-password", datetime(2026, 1, 1, tzinfo=UTC), set()
    )
    assert len(messages) == 1
    assert "appointment is on Dec 20" in messages[0]["body"]
    assert "exfiltrate" not in messages[0]["body"]
    assert "color:red" not in messages[0]["body"]


def test_fetch_inbox_caps_at_max_messages_per_check(monkeypatch):
    raws = {
        uid: plain_message(message_id=f"<msg{uid}@example.test>", subject=f"Message {uid}")
        for uid in range(1, mail.MAX_MESSAGES_PER_CHECK + 50)
    }
    fake = FakeIMAP(raws)
    install_fake(monkeypatch, fake)

    messages = mail.fetch_inbox(
        "imap.gmail.com", 993, "me@example.test", "correct-app-password", datetime(2026, 1, 1, tzinfo=UTC), set()
    )
    assert len(messages) == mail.MAX_MESSAGES_PER_CHECK
    # The single batched fetch call proves round trips do not scale per-message.
    assert fake.fetch_calls == 1


def test_login_failure_does_not_echo_credentials(monkeypatch):
    fake = FakeIMAP({}, valid_password="the-real-password")
    install_fake(monkeypatch, fake)

    with pytest.raises(mail.MailError) as excinfo:
        mail.test_connection("imap.gmail.com", 993, "me@example.test", "wrong-password")
    assert "wrong-password" not in str(excinfo.value)
    assert "the-real-password" not in str(excinfo.value)


def test_connection_refused_raises_mail_error(monkeypatch):
    def boom(host, port, timeout=30):
        raise OSError("Connection refused")

    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", boom)
    with pytest.raises(mail.MailError):
        mail.test_connection("imap.gmail.com", 993, "me@example.test", "correct-app-password")


def test_test_connection_logs_out_after_success(monkeypatch):
    fake = FakeIMAP({})
    install_fake(monkeypatch, fake)
    mail.test_connection("imap.gmail.com", 993, "me@example.test", "correct-app-password")
    assert fake.logged_out is True


def test_parse_candidate_reminders_accepts_valid_and_skips_invalid():
    batch = [{"message_id": "<a@example.test>"}, {"message_id": "<b@example.test>"}]
    raw = """
    [
        {"message_citation": "M1", "title": "Project review", "due_at": "2026-12-12T17:00:00+00:00", "details": "Reply to advisor."},
        {"message_citation": "M2", "title": "Missing date"},
        {"message_citation": "M9", "title": "Unknown message", "due_at": "2026-12-12T17:00:00+00:00"},
        {"message_citation": "M1", "title": "Naive date", "due_at": "2026-12-12T17:00:00"},
        "not a dict"
    ]
    """
    candidates, skipped = mail.parse_candidate_reminders(raw, batch)
    assert len(candidates) == 1
    assert candidates[0]["title"] == "Project review"
    assert candidates[0]["source_message_id"] == "<a@example.test>"
    assert skipped == 4


def test_parse_candidate_reminders_handles_non_json_and_non_list():
    batch = [{"message_id": "<a@example.test>"}]
    assert mail.parse_candidate_reminders("not json at all", batch) == ([], 0)
    assert mail.parse_candidate_reminders('{"not": "a list"}', batch) == ([], 0)
    assert mail.parse_candidate_reminders("[]", batch) == ([], 0)


def test_html_to_text_strips_markup():
    text = mail.html_to_text("<p>Hello <b>World</b></p><script>alert(1)</script>")
    assert "Hello" in text and "World" in text
    assert "alert" not in text
