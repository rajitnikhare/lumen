import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from lumen import research
from lumen.app import IDLE_SECONDS
from lumen.inference import ModelError


def note(client, authorized=True, body="The Paris train leaves on October 20.", category="note"):
    response = client.post(
        "/api/notes",
        json={
            "title": "Travel plans",
            "body": body,
            "authorized": authorized,
            "category": category,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_local_boundary_csrf_and_session(app, client):
    assert client.get("/").status_code == 200
    assert "default-src 'self'" in client.get("/").headers["content-security-policy"]
    assert client.get("/api/dashboard", headers={"Host": "attacker.test"}).status_code == 403
    assert client.get("/api/dashboard", headers={"Origin": "https://evil.test"}).status_code == 403
    assert client.post("/api/lock", headers={"X-Lumen-CSRF": "wrong"}).status_code == 403
    with TestClient(app, base_url="http://127.0.0.1:8765") as other:
        assert other.get("/api/dashboard").status_code == 423


def test_notes_crud_memory_and_permission_revocation(client, app):
    saved = note(client)
    private = note(client, False, body="Secret Paris account 123.")
    app.state.lumen.model.response = "Your train leaves October 20 [S1]."
    turn = client.post("/api/chat", json={"message": "When does the Paris train leave?"}).json()
    assert turn["sources"][0]["record_id"] == saved["id"]
    assert all(source["record_id"] != private["id"] for source in turn["sources"])
    payload = app.state.lumen.model.calls[-1]["data"]
    assert "Secret" not in str(payload)
    assert (
        client.put(f"/api/access/note/{saved['id']}", json={"authorized": False}).status_code == 200
    )
    app.state.lumen.model.response = "I do not have authorized personal information about that."
    assert (
        client.post(
            "/api/chat", json={"message": "When is my train?", "use_history": True}
        ).status_code
        == 200
    )
    payload = app.state.lumen.model.calls[-1]["data"]
    assert payload["sources"] == []
    assert payload["prior_conversation"] == []
    assert (
        client.put(
            f"/api/notes/{saved['id']}",
            json={"title": "Updated trip", "body": "The trip has changed.", "authorized": False},
        ).status_code
        == 200
    )
    assert client.get(f"/api/items/note/{saved['id']}").json()["title"] == "Updated trip"


def test_preferences_are_opt_in_and_not_used_after_revocation(client, app):
    preference = note(client, True, "Use a concise tone.", "preference")
    note(client, False, "My secret preference.", "preference")
    client.post("/api/chat", json={"message": "Hello"})
    payload = app.state.lumen.model.calls[-1]["data"]
    assert len(payload["preferences"]) == 1
    assert payload["preferences"][0]["body"] == "Use a concise tone."
    client.put(f"/api/access/note/{preference['id']}", json={"authorized": False})
    client.post("/api/chat", json={"message": "Hello again", "use_history": True})
    payload = app.state.lumen.model.calls[-1]["data"]
    assert payload["preferences"] == []
    assert payload["prior_conversation"] == []


def configure_semantic(client, app, monkeypatch):
    embedded = []

    async def embed(model, texts):
        embedded.extend(texts)
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(app.state.lumen.model, "embed", embed, raising=False)
    response = client.put(
        "/api/settings",
        json={"model": "test-local:latest", "embedding_model": "test-embed"},
    )
    assert response.status_code == 200, response.text
    return embedded


def test_semantic_chat_supplies_external_document_and_honors_revocation(client, app, monkeypatch):
    saved = client.post(
        "/api/documents?filename=household.txt&authorized=true",
        content=b"Terminate unused memberships. Estimated monthly savings: USD 47.",
    ).json()
    note(client, False, "Private account must not be embedded.")
    question = {"message": "How can I lower my bills?"}
    assert client.post("/api/chat", json=question).json()["sources"] == []
    embedded = configure_semantic(client, app, monkeypatch)
    app.state.lumen.model.response = "Terminate unused memberships to save USD 47 monthly [S1]."
    result = client.post("/api/chat", json=question)
    assert result.status_code == 200, result.text
    turn = result.json()
    assert turn["retrieval"] == {"method": "semantic", "model": "test-embed", "count": 1}
    assert turn["sources"][0]["record_id"] == saved["id"]
    assert "USD 47" in app.state.lumen.model.calls[-1]["data"]["sources"][0]["text"]
    assert "Private account" not in str(embedded)
    client.put(f"/api/access/document/{saved['id']}", json={"authorized": False})
    app.state.lumen.model.response = "I do not have that information."
    result = client.post("/api/chat", json={**question, "use_history": True})
    assert result.status_code == 200
    assert result.json()["sources"] == []
    history = app.state.lumen.model.calls[-1]["data"]["prior_conversation"]
    assert len(history) == 1
    assert history[0]["assistant"] == "A grounded local answer."


@pytest.mark.parametrize("change", ["revoke", "lock", "error"])
def test_semantic_retrieval_does_not_generate_after_access_change_or_error(
    client, app, monkeypatch, change
):
    saved = note(client)
    configure_semantic(client, app, monkeypatch)

    async def embed(model, texts):
        if change == "error":
            raise ModelError("Local embedding failed.")
        if change == "lock":
            app.state.lumen.lock()
        else:
            item = app.state.lumen.vault.get("note", saved["id"])
            item["authorized"] = False
            app.state.lumen.vault.put("note", item)
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(app.state.lumen.model, "embed", embed)
    result = client.post("/api/chat", json={"message": "Paris train"})
    assert result.status_code == {"revoke": 409, "lock": 423, "error": 502}[change]
    assert app.state.lumen.model.calls == []


def test_semantic_settings_preserved_when_omitted_and_disabled_when_blank(client, app, monkeypatch):
    configure_semantic(client, app, monkeypatch)
    result = client.put("/api/settings", json={"model": "test-local:latest"})
    assert result.json()["embedding_model"] == "test-embed"
    result = client.put(
        "/api/settings", json={"model": "test-local:latest", "embedding_model": ""}
    )
    assert result.json()["embedding_model"] == ""


def test_semantic_attachment_does_not_fallback_to_irrelevant_opening_text(client, app, monkeypatch):
    configure_semantic(client, app, monkeypatch)
    saved = client.post(
        "/api/documents?filename=plants.txt&authorized=true",
        content=b"Water the fern once a week.",
    ).json()

    async def embed(model, texts):
        return [[1.0, 0.0] if text.startswith("search_query:") else [0.0, 1.0] for text in texts]

    monkeypatch.setattr(app.state.lumen.model, "embed", embed)
    result = client.post(
        "/api/chat",
        json={"message": "How can I lower my bills?", "document_ids": [saved["id"]]},
    )
    assert result.status_code == 200
    assert result.json()["sources"] == []
    assert app.state.lumen.model.calls[-1]["data"]["sources"] == []


def test_reminders_require_timezone_and_can_be_updated(client):
    fields = {"title": "Capstone", "due_at": "2026-10-20T18:00:00-06:00", "details": "Present"}
    response = client.post("/api/reminders", json=fields)
    assert response.status_code == 200
    item = response.json()
    assert item["due_at"] == "2026-10-21T00:00:00Z"
    response = client.put(f"/api/reminders/{item['id']}", json={**fields, "done": True})
    assert response.json()["done"] is True
    assert (
        client.post("/api/reminders", json={**fields, "due_at": "2026-10-20T18:00:00"}).status_code
        == 422
    )


def test_email_draft_is_editable_and_has_no_send_endpoint(client):
    response = client.post(
        "/api/compose",
        json={
            "recipient": "teacher@example.test",
            "instructions": "Request a meeting.",
            "tone": "formal",
        },
    )
    assert response.status_code == 200
    assert client.get("/api/dashboard").json()["draft"] == []
    fields = {
        "recipient": "teacher@example.test",
        "subject": "Meeting",
        "body": response.json()["body"],
    }
    saved = client.post("/api/drafts", json=fields).json()
    updated = client.put(f"/api/drafts/{saved['id']}", json={**fields, "body": "Edited by me."})
    assert updated.json()["body"] == "Edited by me."
    assert client.post("/api/send", json=fields).status_code == 404


def test_document_requires_explicit_permission_and_summarizes_all_chunks(client, app):
    content = (
        b"First deadline October 20. "
        + b"Supporting material. " * 500
        + b"Final deadline October 31."
    )
    saved = client.post("/api/documents?filename=plan.txt", content=content).json()
    assert not saved["authorized"]
    assert client.post(f"/api/documents/{saved['id']}/summary", json={}).status_code == 403
    assert app.state.lumen.model.calls == []
    client.put(f"/api/access/document/{saved['id']}", json={"authorized": True})
    result = client.post(f"/api/documents/{saved['id']}/summary", json={})
    assert result.status_code == 200
    sections = [
        section
        for call in app.state.lumen.model.calls
        for section in call["data"].get("sections", [])
    ]
    original = client.get(f"/api/items/document/{saved['id']}").json()
    assert len(sections) == len(original["chunks"])
    assert any("Final deadline October 31." in section["text"] for section in sections)
    assert original["summary"]
    assert "chunks" not in client.get("/api/dashboard").json()["document"][0]


@pytest.mark.parametrize(
    "text",
    [
        "Your train leaves tomorrow [S999].",
        "Your train leaves tomorrow [S1, S999].",
    ],
)
def test_invalid_source_labels_are_not_saved(client, app, text):
    note(client)
    app.state.lumen.model.response = text
    response = client.post("/api/chat", json={"message": "Paris train"})
    assert response.status_code == 502
    assert client.get("/api/dashboard").json()["chat"] == []


def test_delete_approval_is_frozen_single_use_and_revision_bound(client):
    saved = note(client)
    path = f"/api/delete/note/{saved['id']}/preview"
    preview = client.post(path).json()
    assert client.get(f"/api/items/note/{saved['id']}").status_code == 200
    client.put(
        f"/api/notes/{saved['id']}",
        json={"title": "Changed", "body": "Changed content", "authorized": True},
    )
    assert client.post(f"/api/approvals/{preview['id']}/confirm").status_code == 409
    preview = client.post(path).json()
    assert client.post(f"/api/approvals/{preview['id']}/confirm").json()["ok"]
    assert client.post(f"/api/approvals/{preview['id']}/confirm").status_code == 409
    assert client.get(f"/api/items/note/{saved['id']}").status_code == 404


def test_external_search_only_after_exact_query_approval(client, app, monkeypatch):
    calls = []

    async def fake_search(query, api_key):
        calls.append((query, api_key))
        return [
            {
                "citation": "W1",
                "title": "Synthetic source",
                "url": "https://example.test",
                "text": "Public reference",
            }
        ]

    monkeypatch.setattr(research, "search", fake_search)
    note(client, True, "A private account number that must never reach Brave.")
    preview = client.post("/api/research/preview", json={"query": "public sleep research"}).json()
    assert calls == []
    assert preview["query"] == "public sleep research"
    app.state.lumen.model.response = "The snippet suggests further reading [W1]."
    result = client.post(f"/api/approvals/{preview['id']}/confirm")
    assert result.status_code == 200
    assert calls == [("public sleep research", "synthetic-key")]
    assert "private account" not in str(app.state.lumen.model.calls[-1]["data"])
    assert client.post(f"/api/approvals/{preview['id']}/confirm").status_code == 409
    assert len(calls) == 1


def test_cancelled_and_expired_approvals_do_not_contact_provider(client, app, monkeypatch):
    async def unexpected_search(*args):
        pytest.fail("Cancelled or expired search contacted provider")

    monkeypatch.setattr(research, "search", unexpected_search)
    preview = client.post("/api/research/preview", json={"query": "safe public query"}).json()
    assert client.delete(f"/api/approvals/{preview['id']}").status_code == 200
    assert client.post(f"/api/approvals/{preview['id']}/confirm").status_code == 409
    preview = client.post("/api/research/preview", json={"query": "safe public query"}).json()
    app.state.lumen.pending[preview["id"]]["expires"] = time.monotonic() - 1
    assert client.post(f"/api/approvals/{preview['id']}/confirm").status_code == 409


def test_search_errors_explicit_no_retry_and_partial_sources_retained(client, app, monkeypatch):
    calls = []

    async def broken_search(query, key):
        calls.append(query)
        raise research.ResearchError("Network failed. No retry.")

    monkeypatch.setattr(research, "search", broken_search)
    preview = client.post("/api/research/preview", json={"query": "public science"}).json()
    assert client.post(f"/api/approvals/{preview['id']}/confirm").status_code == 502
    assert client.post(f"/api/approvals/{preview['id']}/confirm").status_code == 409
    assert len(calls) == 1

    async def available_search(query, key):
        return [
            {"citation": "W1", "title": "Reference", "url": "https://example.test", "text": "Data"}
        ]

    async def failed_model(*args):
        raise ModelError("Ollama unavailable")

    monkeypatch.setattr(research, "search", available_search)
    app.state.lumen.model.generate = failed_model
    preview = client.post("/api/research/preview", json={"query": "public science"}).json()
    assert client.post(f"/api/approvals/{preview['id']}/confirm").status_code == 502
    saved = client.get("/api/dashboard").json()["research"][0]
    assert saved["status"] == "summary_failed"
    assert saved["sources"][0]["citation"] == "W1"
    assert saved["error"] == "Ollama unavailable"


def test_invalid_research_answer_is_not_retained(client, app, monkeypatch):
    async def fake_search(query, key):
        return [
            {"citation": "W1", "title": "Reference", "url": "https://example.test", "text": "Data"}
        ]

    monkeypatch.setattr(research, "search", fake_search)
    app.state.lumen.model.response = "An invented claim [W999]."
    preview = client.post("/api/research/preview", json={"query": "public topic"}).json()
    assert client.post(f"/api/approvals/{preview['id']}/confirm").status_code == 502
    saved = client.get("/api/dashboard").json()["research"][0]
    assert saved["status"] == "summary_failed"
    assert saved["summary"] == ""
    assert saved["sources"][0]["citation"] == "W1"


@pytest.mark.parametrize("query", ["me@example.test booking", "number 123-45-6789", "   "])
def test_obvious_private_identifiers_rejected(client, query):
    assert client.post("/api/research/preview", json={"query": query}).status_code == 400


def test_api_key_never_returned_and_settings_can_remove_it(client):
    assert client.get("/api/settings").json() == {
        "model": "test-local:latest",
        "embedding_model": "",
        "brave_configured": True,
    }
    assert client.get("/api/items/settings/settings").status_code == 404
    assert (
        client.put("/api/settings", json={"model": "test-local:latest", "brave_key": ""}).json()[
            "brave_configured"
        ]
        is False
    )
    assert client.post("/api/research/preview", json={"query": "public science"}).status_code == 400


def test_removing_brave_key_does_not_require_ollama(client, app):
    async def offline_models():
        raise ModelError("Synthetic Ollama outage")

    app.state.lumen.model.models = offline_models
    response = client.put("/api/settings", json={"model": "test-local:latest", "brave_key": ""})
    assert response.status_code == 200, response.text
    assert response.json()["brave_configured"] is False
    assert app.state.lumen.settings()["model"] == "test-local:latest"


def test_changing_model_still_validates_it_against_ollama(client, app):
    async def offline_models():
        raise ModelError("Synthetic Ollama outage")

    app.state.lumen.model.models = offline_models
    response = client.put("/api/settings", json={"model": "other-local:latest"})
    assert response.status_code == 502
    assert app.state.lumen.settings()["model"] == "test-local:latest"


def test_auto_lock_does_not_count_polling_and_clears_pending(client, app):
    state = app.state.lumen
    client.post("/api/research/preview", json={"query": "public science"})
    state.last_action = time.monotonic() - IDLE_SECONDS - 1
    assert client.get("/api/session").json()["unlocked"] is False
    assert client.get("/api/dashboard").status_code == 423
    assert state.pending == {}
    assert not state.vault.unlocked


def test_lock_during_local_inference_discards_result(client, app):
    async def locking_model(*args):
        app.state.lumen.lock()
        return "This must not be saved."

    app.state.lumen.model.generate = locking_model
    assert client.post("/api/chat", json={"message": "Hello"}).status_code == 423
    assert not app.state.lumen.vault.unlocked


def test_access_revocation_during_inference_discards_result(client, app):
    saved = note(client)

    async def revoking_model(*args):
        item = app.state.lumen.vault.get("note", saved["id"])
        item["authorized"] = False
        app.state.lumen.vault.put("note", item)
        return "Private answer [S1]."

    app.state.lumen.model.generate = revoking_model
    assert client.post("/api/chat", json={"message": "Paris train"}).status_code == 409
    assert client.get("/api/dashboard").json()["chat"] == []


def test_explicit_shared_text_and_app_context_reach_only_local_inference(client, app):
    text = "A synthetic email requesting a reply about Project Orchid."
    response = client.post(
        "/api/chat",
        json={
            "message": "Suggest my next step.",
            "shared_text": text,
            "app_name": "Mail",
        },
    )
    assert response.status_code == 200
    payload = app.state.lumen.model.calls[-1]["data"]
    assert payload["shared_text"] == text
    assert payload["app_name"] == "Mail"
    turn = client.get("/api/dashboard").json()["chat"][0]
    assert turn["shared_text"] == text
    assert turn["app_name"] == "Mail"
    assert text.encode() not in app.state.lumen.vault.path.read_bytes()


def test_shared_file_is_permission_checked_and_used_without_keyword_match(client, app):
    document = client.post(
        "/api/documents?filename=orchid.txt",
        content=b"A unique synthetic file containing Project Orchid deadlines.",
    ).json()
    body = {"message": "Suggest how to organize this.", "document_ids": [document["id"]]}
    assert client.post("/api/chat", json=body).status_code == 403
    assert app.state.lumen.model.calls == []
    client.put(f"/api/access/document/{document['id']}", json={"authorized": True})
    response = client.post("/api/chat", json=body)
    assert response.status_code == 200
    assert response.json()["sources"][0]["record_id"] == document["id"]
    payload = app.state.lumen.model.calls[-1]["data"]
    assert "Project Orchid" in payload["sources"][0]["text"]
    client.put(f"/api/access/document/{document['id']}", json={"authorized": False})
    assert client.post("/api/chat", json=body).status_code == 403


def test_health_is_nonprivate_and_does_not_unlock_or_refresh_activity(client, app):
    state = app.state.lumen
    state.last_action = time.monotonic() - 100
    last_action = state.last_action
    assert client.get("/api/health").json() == {"application": "lumen", "protocol": 1}
    assert state.last_action == last_action


def test_large_json_rejected_before_parsing(client):
    assert client.post("/api/notes", content=b"x" * (128 * 1024 + 1)).status_code == 413


def test_busy_model_reports_conflict_without_saving(client, app):
    async def take_lock():
        await app.state.lumen.ai_lock.acquire()

    asyncio.run(take_lock())
    try:
        assert client.post("/api/chat", json={"message": "Hello"}).status_code == 409
    finally:
        app.state.lumen.ai_lock.release()
    assert client.get("/api/dashboard").json()["chat"] == []
