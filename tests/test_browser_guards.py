import os
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from conftest import FakeModel
from playwright.sync_api import expect, sync_playwright

from lumen.app import create_app
from lumen.inference import ModelError

pytestmark = pytest.mark.skipif(
    os.getenv("LUMEN_BROWSER_TESTS") != "1", reason="Opt-in isolated browser checks."
)


@pytest.fixture
def workspace(tmp_path):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    app = create_app(tmp_path, port)
    app.state.lumen.model = FakeModel()
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]})
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        else:
            pytest.fail("Isolated browser server did not start")
        with sync_playwright() as playwright:
            channel = "chrome" if Path("/Applications/Google Chrome.app").exists() else None
            browser = playwright.chromium.launch(channel=channel, headless=True)
            try:
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{port}")
                page.locator("#passphrase").fill("synthetic browser passphrase")
                page.locator("#unlock-form button").click()
                expect(page.locator("#workspace")).to_be_visible()
                expect(page.locator("#unlock-button")).to_be_enabled()
                yield app.state.lumen, page
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        assert not thread.is_alive()


@pytest.mark.parametrize("failure", ["offline", "removed"])
def test_saved_model_readiness_does_not_silently_replace_model(workspace, failure):
    state, page = workspace

    async def models():
        if failure == "offline":
            raise ModelError("Synthetic Ollama outage")
        return ["other-local:latest"]

    state.model.models = models
    page.evaluate("async () => await ensureModel()")
    expect(page.locator("#model-setup")).to_be_visible()
    expect(page.locator("#model-setup-text")).to_contain_text(
        "outage" if failure == "offline" else "unavailable"
    )
    assert state.settings()["model"] == "test-local:latest"
    page.locator("[data-chat-mode=note]").click()
    page.locator("#chat-message").fill("A note without AI.")
    page.locator("#chat-submit").click()
    expect(page.locator("#chat-tool-feedback")).to_contain_text("Saved")
    assert len(state.vault.all("note")) == 1
    assert state.model.calls == []


def test_sharing_receipts_reject_replacement_sessions_and_replays(workspace):
    state, page = workspace
    context = page.evaluate("async () => await window.lumenMac.prepareSharing()")
    state.generation += 1
    assert page.evaluate("window.lumenMac.canShare()") is True
    assert page.evaluate(
        "async context => await window.lumenMac.validateSharing(context)", context
    ) is False
    assert page.evaluate(
        "async context => await window.lumenMac.shareText({text:'Stale text',mode:'ask'},context)",
        context,
    ) is False
    assert page.evaluate(
        "async context => await window.lumenMac.shareFile({name:'stale.txt',base64:'eA=='},context)",
        context,
    ) is False
    expect(page.locator("#shared-text")).to_have_value("")
    fresh = page.evaluate("async () => await window.lumenMac.prepareSharing()")
    script = "async context => await window.lumenMac.shareText({text:'Fresh text',mode:'note'},context)"
    assert page.evaluate(script, fresh) is True
    assert page.evaluate(script, fresh) is False
    expect(page.locator("#shared-text")).to_have_value("Fresh text")
    assert state.model.calls == []
    assert state.vault.all("document") == []


def test_clipboard_provider_is_not_called_when_server_session_is_locked(workspace):
    state, page = workspace
    page.evaluate("""() => {
      window.clipboardReads = 0;
      Object.defineProperty(navigator, 'clipboard', {value: {
        readText: async () => { window.clipboardReads += 1; return 'Synthetic clipboard'; }
      }});
    }""")
    state.lock()
    assert page.evaluate("window.lumenMac.canShare()") is True
    page.locator("#share-clipboard").click()
    expect(page.locator("#vault-screen")).to_be_visible()
    assert page.evaluate("window.clipboardReads") == 0
    expect(page.locator("#shared-text")).to_have_value("")


def test_clipboard_delivery_is_discarded_after_lock_during_read(workspace):
    state, page = workspace
    page.evaluate("""() => {
      Object.defineProperty(navigator, 'clipboard', {value: {
        readText: () => new Promise(resolve => {
          window.finishClipboard = resolve;
          document.body.dataset.clipboardWaiting = 'true';
        })
      }});
    }""")
    page.locator("#share-clipboard").click()
    expect(page.locator("body")).to_have_attribute("data-clipboard-waiting", "true")
    state.lock()
    page.evaluate("window.finishClipboard('Synthetic stale clipboard')")
    expect(page.locator("#vault-screen")).to_be_visible()
    expect(page.locator("#shared-text")).to_have_value("")
