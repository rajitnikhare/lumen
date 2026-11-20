import time


def test_voice_authorization_is_session_bound_without_model_or_record_writes(client, app):
    state = app.state.lumen
    state.last_action = time.monotonic() - 100
    previous = state.last_action
    response = client.post("/api/voice/authorize")
    assert response.status_code == 200
    assert response.json() == {"vault_generation": state.generation}
    assert state.last_action > previous
    assert state.model.calls == []
    assert state.vault.all("chat") == []
    assert state.vault.all("note") == []


def test_voice_authorization_requires_csrf_and_unlock(client):
    assert client.post(
        "/api/voice/authorize", headers={"X-Lumen-CSRF": "incorrect"}
    ).status_code == 403
    assert client.post("/api/lock").status_code == 200
    assert client.post("/api/voice/authorize").status_code == 423
