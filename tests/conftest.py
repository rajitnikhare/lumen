import pytest
from fastapi.testclient import TestClient

from lumen.app import create_app

PASSPHRASE = "a long synthetic test passphrase"


class FakeModel:
    def __init__(self):
        self.calls = []
        self.response = "A grounded local answer."

    async def models(self):
        return ["test-local:latest"]

    async def generate(self, model, task, data):
        self.calls.append({"model": model, "task": task, "data": data})
        return self.response


@pytest.fixture
def app(tmp_path):
    application = create_app(tmp_path, port=8765)
    application.state.lumen.model = FakeModel()
    return application


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://127.0.0.1:8765") as browser:
        browser.headers["X-Lumen-CSRF"] = browser.get("/api/session").json()["csrf"]
        assert browser.post("/api/unlock", json={"passphrase": PASSPHRASE}).status_code == 200
        assert (
            browser.put(
                "/api/settings", json={"model": "test-local:latest", "brave_key": "synthetic-key"}
            ).status_code
            == 200
        )
        yield browser
