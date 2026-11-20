import asyncio

import httpx
import pytest
from conftest import PASSPHRASE

from lumen import research
from lumen.inference import ModelError


def invalidate_document(state, identifier, change):
    if change == "lock":
        state.lock()
        return
    if change == "session":
        state.generation += 1
        return
    if change == "delete":
        state.vault.delete("document", identifier)
        return
    document = state.vault.get("document", identifier)
    if change == "revoke":
        document["authorized"] = False
    else:
        document["updated_at"] = "changed-revision"
    state.vault.put("document", document)


@pytest.mark.parametrize("stage", ["map", "reduce"])
@pytest.mark.parametrize("change", ["revoke", "delete", "edit", "lock", "session"])
def test_summary_stops_at_each_invalidated_checkpoint(client, app, stage, change):
    document = client.post(
        "/api/documents?filename=synthetic.txt&authorized=true",
        content=b"Synthetic fact. " * 700,
    ).json()
    state = app.state.lumen
    original = state.vault.get("document", document["id"])
    original["summary"] = "Earlier saved summary."
    state.vault.put("document", original)
    map_calls = (len(original["chunks"]) + 1) // 2
    stop_at = map_calls if stage == "map" else map_calls + 1
    calls = []

    async def generate(model, task, data):
        calls.append(data)
        if len(calls) == stop_at:
            invalidate_document(state, document["id"], change)
        return "Synthetic summary."

    state.model.generate = generate
    response = client.post(f"/api/documents/{document['id']}/summary", json={})
    assert response.status_code == (423 if change in {"lock", "session"} else 409)
    assert len(calls) == stop_at
    if change == "lock":
        assert client.post("/api/unlock", json={"passphrase": PASSPHRASE}).status_code == 200
    current = state.vault.get("document", document["id"])
    if change == "delete":
        assert current is None
    else:
        assert current["summary"] == "Earlier saved summary."


async def public_sources(query, key):
    return [{"citation": "W1", "title": "Synthetic reference",
             "url": "https://example.test", "text": "Public guidance."}]


async def delete_research(app, client, identifier):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:8765",
        cookies={"lumen_session": client.cookies.get("lumen_session")},
        headers={"X-Lumen-CSRF": client.headers["X-Lumen-CSRF"]},
    ) as other:
        preview = await other.post(f"/api/delete/research/{identifier}/preview")
        deleted = await other.post(f"/api/approvals/{preview.json()['id']}/confirm")
        assert deleted.status_code == 200
    assert app.state.lumen.vault.get("research", identifier) is None


@pytest.mark.parametrize("model_fails", [False, True])
def test_deleted_research_is_not_recreated(client, app, monkeypatch, model_fails):
    state = app.state.lumen
    monkeypatch.setattr(research, "search", public_sources)

    async def generate(model, task, data):
        identifier = state.vault.all("research")[0]["id"]
        await delete_research(app, client, identifier)
        if model_fails:
            raise ModelError("Synthetic failure")
        return "A supported finding [W1]."

    state.model.generate = generate
    preview = client.post("/api/research/preview", json={"query": "public topic"}).json()
    response = client.post(f"/api/approvals/{preview['id']}/confirm")
    assert response.status_code == 409
    assert state.vault.all("research") == []
    assert client.post(f"/api/approvals/{preview['id']}/confirm").status_code == 409


def test_busy_research_retains_evidence_with_failure_reason(client, app, monkeypatch):
    state = app.state.lumen
    monkeypatch.setattr(research, "search", public_sources)
    preview = client.post("/api/research/preview", json={"query": "public topic"}).json()
    asyncio.run(state.ai_lock.acquire())
    try:
        response = client.post(f"/api/approvals/{preview['id']}/confirm")
    finally:
        state.ai_lock.release()
    assert response.status_code == 409
    result = state.vault.all("research")[0]
    assert result["status"] == "summary_failed"
    assert "already running" in result["error"]
    assert result["sources"][0]["citation"] == "W1"


def test_settings_embedding_obeys_admission_and_releases_slot(client, app, monkeypatch):
    state = app.state.lumen
    calls = []

    async def embed(model, texts):
        assert state.ai_lock.locked()
        calls.append(texts)
        raise ModelError("Synthetic embedding failure")

    monkeypatch.setattr(state.model, "embed", embed, raising=False)
    fields = {"model": "test-local:latest", "embedding_model": "test-embed"}
    asyncio.run(state.ai_lock.acquire())
    try:
        assert client.put("/api/settings", json=fields).status_code == 409
    finally:
        state.ai_lock.release()
    assert calls == []
    assert client.put("/api/settings", json=fields).status_code == 502
    assert len(calls) == 1
    assert not state.ai_lock.locked()
    assert state.settings().get("embedding_model", "") == ""
    assert client.post("/api/chat", json={"message": "Hello"}).status_code == 200


def test_sharing_authorization_is_live_session_bound_and_read_free(client, app):
    state = app.state.lumen
    generation = state.generation
    assert client.post("/api/sharing/authorize").json() == {"vault_generation": generation}
    assert state.model.calls == []
    assert all(state.vault.all(kind) == [] for kind in ("chat", "note", "document"))
    assert client.post(
        "/api/sharing/authorize", headers={"X-Lumen-CSRF": "wrong"}
    ).status_code == 403
    assert client.post("/api/lock").status_code == 200
    assert client.post("/api/sharing/authorize").status_code == 423
    assert client.post("/api/unlock", json={"passphrase": PASSPHRASE}).status_code == 200
    assert client.post("/api/sharing/authorize").json()["vault_generation"] != generation
