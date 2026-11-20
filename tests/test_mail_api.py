import json
from datetime import UTC, datetime

from lumen import mail
from lumen.app import record
from lumen.inference import ModelError


def test_mail_account_defaults_and_requires_credentials(client):
    account = client.get("/api/mail/account").json()
    assert account == {
        "host": mail.IMAP_HOST_DEFAULT,
        "port": mail.IMAP_PORT_DEFAULT,
        "username": "",
        "configured": False,
    }
    assert client.put("/api/mail/account", json={"username": ""}).status_code == 400
    assert (
        client.put("/api/mail/account", json={"username": "me@example.test"}).status_code == 400
    )


def test_mail_account_save_validates_connection_and_never_returns_the_password(
    client, monkeypatch
):
    calls = []

    def fake_test_connection(host, port, username, app_password):
        calls.append((host, port, username, app_password))

    monkeypatch.setattr(mail, "test_connection", fake_test_connection)
    response = client.put(
        "/api/mail/account",
        json={
            "host": "imap.gmail.com",
            "port": 993,
            "username": "me@example.test",
            "app_password": "a synthetic app password",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "host": "imap.gmail.com",
        "port": 993,
        "username": "me@example.test",
        "configured": True,
    }
    assert "app_password" not in body
    assert calls == [("imap.gmail.com", 993, "me@example.test", "a synthetic app password")]

    # A later save that omits the password keeps the previously saved one and still validates.
    calls.clear()
    response = client.put("/api/mail/account", json={"username": "me@example.test"})
    assert response.status_code == 200
    assert calls == [("imap.gmail.com", 993, "me@example.test", "a synthetic app password")]

    disconnected = client.put("/api/mail/account", json={"disconnect": True}).json()
    assert disconnected == {
        "host": mail.IMAP_HOST_DEFAULT,
        "port": mail.IMAP_PORT_DEFAULT,
        "username": "",
        "configured": False,
    }


def test_mail_account_save_surfaces_connection_failure_without_saving(client, monkeypatch):
    def failing_test_connection(host, port, username, app_password):
        raise mail.MailError("Sign-in failed.")

    monkeypatch.setattr(mail, "test_connection", failing_test_connection)
    response = client.put(
        "/api/mail/account",
        json={"username": "me@example.test", "app_password": "wrong"},
    )
    assert response.status_code == 502
    assert client.get("/api/mail/account").json()["configured"] is False


def configure_mail_account(client, monkeypatch):
    monkeypatch.setattr(mail, "test_connection", lambda *args, **kwargs: None)
    response = client.put(
        "/api/mail/account",
        json={"username": "me@example.test", "app_password": "a synthetic app password"},
    )
    assert response.status_code == 200, response.text


def test_check_mail_requires_account_and_model(client, app, monkeypatch):
    assert client.post("/api/mail/check").status_code == 400
    configure_mail_account(client, monkeypatch)
    app.state.lumen.vault.put("settings", {**app.state.lumen.settings(), "model": ""})
    assert client.post("/api/mail/check").status_code == 400


def test_check_mail_imports_messages_and_extracts_candidate_reminders(client, app, monkeypatch):
    configure_mail_account(client, monkeypatch)
    fetched = [
        {
            "message_id": "<a@example.test>",
            "subject": "Project Cedar",
            "sender": "advisor@example.test",
            "received_at": datetime.now(UTC).isoformat(),
            "body": "Project Cedar is due December 12, 2026 at 5pm.",
            "truncated": False,
        }
    ]
    calls = []

    def fake_fetch_inbox(host, port, username, app_password, since, known_message_ids):
        calls.append(known_message_ids)
        return fetched

    monkeypatch.setattr(mail, "fetch_inbox", fake_fetch_inbox)
    app.state.lumen.model.response = json.dumps(
        [
            {
                "message_citation": "M1",
                "title": "Project Cedar due",
                "due_at": "2026-12-12T17:00:00+00:00",
                "details": "Project Cedar deliverable.",
            }
        ]
    )
    response = client.post("/api/mail/check")
    assert response.status_code == 200, response.text
    assert response.json() == {"imported": 1, "candidates": 1, "skipped_invalid": 0}
    assert calls == [set()]

    dashboard = client.get("/api/dashboard").json()
    assert len(dashboard["mail_message"]) == 1
    assert "body" not in dashboard["mail_message"][0]
    assert dashboard["mail_message"][0]["subject"] == "Project Cedar"
    assert len(dashboard["candidate_reminder"]) == 1
    assert dashboard["candidate_reminder"][0]["title"] == "Project Cedar due"

    # Checking again passes the already-known message_id so it is not re-imported.
    client.post("/api/mail/check")
    assert calls[-1] == {"<a@example.test>"}


def test_check_mail_skips_batch_on_model_error_but_keeps_import(client, app, monkeypatch):
    configure_mail_account(client, monkeypatch)
    monkeypatch.setattr(
        mail,
        "fetch_inbox",
        lambda *args, **kwargs: [
            {
                "message_id": "<a@example.test>",
                "subject": "Hello",
                "sender": "a@example.test",
                "received_at": datetime.now(UTC).isoformat(),
                "body": "No dates here.",
                "truncated": False,
            }
        ],
    )

    async def failing_generate(model, task, data):
        raise ModelError("Synthetic outage")

    app.state.lumen.model.generate = failing_generate
    response = client.post("/api/mail/check")
    assert response.status_code == 200
    assert response.json() == {"imported": 1, "candidates": 0, "skipped_invalid": 0}
    assert len(client.get("/api/dashboard").json()["mail_message"]) == 1


def seed_candidate_reminder(app, **overrides):
    fields = {
        "title": "Project Cedar due",
        "due_at": "2026-12-12T17:00:00+00:00",
        "details": "Project Cedar deliverable.",
        "source_message_id": "<a@example.test>",
        "status": "pending",
        **overrides,
    }
    return app.state.lumen.vault.put("candidate_reminder", record(**fields))


def test_candidate_reminder_accept_creates_reminder_and_removes_candidate(client, app):
    candidate = seed_candidate_reminder(app)
    response = client.post(f"/api/candidate-reminders/{candidate['id']}/accept", json={})
    assert response.status_code == 200, response.text
    reminder = response.json()
    assert reminder["title"] == "Project Cedar due"
    assert reminder["due_at"].startswith("2026-12-12T17:00:00")
    assert client.get("/api/dashboard").json()["candidate_reminder"] == []
    assert any(item["id"] == reminder["id"] for item in client.get("/api/dashboard").json()["reminder"])


def test_candidate_reminder_accept_allows_edits_before_saving(client, app):
    candidate = seed_candidate_reminder(app)
    response = client.post(
        f"/api/candidate-reminders/{candidate['id']}/accept",
        json={"title": "Edited title", "details": "Edited details."},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Edited title"
    assert response.json()["details"] == "Edited details."


def test_candidate_reminder_accept_missing_returns_404(client):
    assert client.post("/api/candidate-reminders/missing/accept", json={}).status_code == 404


def test_candidate_reminder_discard_is_direct_not_approval_based(client, app):
    candidate = seed_candidate_reminder(app)
    response = client.delete(f"/api/candidate-reminders/{candidate['id']}")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert client.get("/api/dashboard").json()["candidate_reminder"] == []
    assert client.delete(f"/api/candidate-reminders/{candidate['id']}").status_code == 404


def seed_mail_message(app, **overrides):
    fields = {
        "message_id": "<a@example.test>",
        "subject": "Flight confirmation",
        "sender": "airline@example.test",
        "received_at": datetime.now(UTC).isoformat(),
        "body": "Your flight to Boston departs on December 20, 2026.",
        "truncated": False,
        "authorized": True,
        **overrides,
    }
    return app.state.lumen.vault.put("mail_message", record(**fields))


def test_chat_uses_authorized_mail_messages_in_retrieval(client, app):
    seed_mail_message(app)
    app.state.lumen.model.response = "Your flight departs December 20 [S1]."
    turn = client.post("/api/chat", json={"message": "When does my flight to Boston depart?"}).json()
    assert turn["sources"][0]["kind"] == "mail_message"
    assert turn["sources"][0]["title"] == "Flight confirmation"


def test_revoking_mail_access_excludes_it_from_retrieval(client, app):
    mail_message = seed_mail_message(app)
    assert client.put(
        f"/api/access/mail_message/{mail_message['id']}", json={"authorized": False}
    ).json() == {"authorized": False}
    app.state.lumen.model.response = "I do not have that information."
    turn = client.post("/api/chat", json={"message": "When does my flight to Boston depart?"}).json()
    assert turn["sources"] == []


def test_mail_message_can_be_deleted_through_the_existing_approval_flow(client, app):
    mail_message = seed_mail_message(app)
    preview = client.post(f"/api/delete/mail_message/{mail_message['id']}/preview").json()
    assert preview["title"] == "Flight confirmation"
    assert client.post(f"/api/approvals/{preview['id']}/confirm").json()["ok"]
    assert client.get(f"/api/items/mail_message/{mail_message['id']}").status_code == 404


def test_mail_message_body_never_appears_in_dashboard_listing(client, app):
    seed_mail_message(app)
    dashboard = client.get("/api/dashboard").json()
    assert len(dashboard["mail_message"]) == 1
    assert "body" not in dashboard["mail_message"][0]
    # Full body is still available on request, same as document extracted text.
    item = client.get(f"/api/items/mail_message/{dashboard['mail_message'][0]['id']}").json()
    assert "Boston" in item["body"]
