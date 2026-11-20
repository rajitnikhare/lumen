import os

import pytest
from fastapi.testclient import TestClient

from lumen.app import create_app

pytestmark = pytest.mark.skipif(
    not os.getenv("LUMEN_LIVE_MODEL"), reason="Opt-in real local Ollama smoke check."
)


def test_live_authorized_qa_summary_and_email_draft(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        client.headers["X-Lumen-CSRF"] = client.get("/api/session").json()["csrf"]
        assert (
            client.post(
                "/api/unlock", json={"passphrase": "synthetic live test passphrase"}
            ).status_code
            == 200
        )
        settings = client.put("/api/settings", json={"model": os.environ["LUMEN_LIVE_MODEL"]})
        assert settings.status_code == 200, settings.text
        document = client.post(
            "/api/documents?filename=orchid.txt&authorized=true",
            content=b"Project Orchid's final submission deadline is October 20, 2026. "
            b"The budget is 300 USD. The presentation is in Room Cedar.",
        ).json()
        summary = client.post(f"/api/documents/{document['id']}/summary", json={})
        assert summary.status_code == 200, summary.text
        text = summary.json()["summary"]
        assert "20" in text and ("October" in text or "Oct" in text), text
        assert "[S1]" in text, text
        answer = client.post(
            "/api/chat",
            json={"message": "What is Project Orchid's final submission deadline?"},
        )
        assert answer.status_code == 200, answer.text
        text = answer.json()["answer"]
        assert "20" in text and ("October" in text or "Oct" in text), text
        assert "[S1]" in text, text
        draft = client.post(
            "/api/compose",
            json={
                "instructions": "Write a short email asking my advisor for a meeting about Project Orchid. "
                "Do not invent a meeting date or time.",
                "tone": "warm and professional",
            },
        )
        assert draft.status_code == 200, draft.text
        assert "Orchid" in draft.json()["body"]
        assert client.get("/api/dashboard").json()["draft"] == []
        advice = client.post(
            "/api/chat",
            json={
                "message": "What should I do next in Mail? Suggest one practical step; do not send anything.",
                "app_name": "Mail",
                "shared_text": "A synthetic email asks me to confirm attendance at a meeting. "
                "I need to check my calendar before committing.",
            },
        )
        assert advice.status_code == 200, advice.text
        assert any(
            term in advice.json()["answer"].lower() for term in ("calendar", "reply", "draft")
        ), advice.text
