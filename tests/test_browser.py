import os
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from conftest import FakeModel
from playwright.sync_api import expect, sync_playwright

from lumen import research
from lumen.app import create_app

pytestmark = pytest.mark.skipif(
    os.getenv("LUMEN_BROWSER_TESTS") != "1", reason="Opt-in local browser check."
)


def test_dashboard_workflows_and_mobile_layout(tmp_path, monkeypatch):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = create_app(tmp_path, port)
    app.state.lumen.model = FakeModel()

    async def fake_embed(model, texts):
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(app.state.lumen.model, "embed", fake_embed, raising=False)
    search_calls = []

    async def fake_search(query, key):
        search_calls.append(query)
        return [
            {
                "citation": "W1",
                "title": "Synthetic reference",
                "url": "https://example.test/reference",
                "text": "Public research snippet.",
            }
        ]

    monkeypatch.setattr(research, "search", fake_search)
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]})
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(trust_env=False) as probe:
            for _ in range(100):
                if server.started:
                    assert probe.get(base).status_code == 200
                    break
                time.sleep(0.05)
            else:
                pytest.fail("Test server did not start.")
        with sync_playwright() as playwright:
            channel = "chrome" if Path("/Applications/Google Chrome.app").exists() else None
            browser = playwright.chromium.launch(channel=channel, headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1050})
            errors = []
            external = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "request",
                lambda request: (
                    external.append(request.url) if not request.url.startswith(base) else None
                ),
            )
            page.goto(base)
            page.locator("#passphrase").fill("a browser test passphrase")
            page.locator("#unlock-form button").click()
            expect(page.locator("#workspace")).to_be_visible()

            page.locator(".sidebar [data-page=settings]").click()
            page.locator("#refresh-models").click()
            expect(page.locator("#model-select")).to_have_value("test-local:latest")
            page.locator("#model-settings-form button[type=submit]").click()
            expect(page.locator("#model-settings-form button[type=submit]")).to_be_enabled()
            page.locator("#brave-key").fill("synthetic-key")
            page.locator("#research-settings-form button[type=submit]").click()
            expect(page.locator("#brave-status")).to_contain_text("saved in the encrypted vault")
            page.locator("#embedding-model").fill("test-embed")
            with page.expect_response(
                lambda response: response.url.endswith("/api/settings")
                and response.request.method == "PUT"
            ) as saved_settings:
                page.locator("#embedding-settings-form button[type=submit]").click()
            assert saved_settings.value.json()["embedding_model"] == "test-embed"
            expect(page.locator("#embedding-settings-form button[type=submit]")).to_be_enabled()
            page.locator(".sidebar [data-page=saved]").click()
            page.locator(".sidebar [data-page=settings]").click()
            expect(page.locator("#embedding-settings-form button[type=submit]")).to_be_enabled()
            expect(page.locator("#embedding-model")).to_have_value("test-embed")
            page.locator("#embedding-model").fill("")
            with page.expect_response(
                lambda response: response.url.endswith("/api/settings")
                and response.request.method == "PUT"
            ) as saved_settings:
                page.locator("#embedding-settings-form button[type=submit]").click()
            assert saved_settings.value.json()["embedding_model"] == ""
            expect(page.locator("#embedding-settings-form button[type=submit]")).to_be_enabled()

            page.locator(".sidebar [data-page=saved]").click()
            page.locator(".saved-tabs [data-saved-tab=notes]").click()
            page.locator("#new-note").click()
            page.locator("#note-title").fill("Orchid travel")
            page.locator("#note-body").fill("The Paris train leaves October 20.")
            page.locator("#note-authorized").check()
            page.locator("#note-form button[type=submit]").click()
            expect(page.locator("#note-list")).to_contain_text("Orchid travel")
            expect(page.locator("#note-list")).to_contain_text("In Lumen's memory")

            page.locator(".saved-tabs [data-saved-tab=documents]").click()
            page.locator("#toggle-upload-form").click()
            page.locator("#document-file").set_input_files(
                {
                    "name": "orchid.txt",
                    "mimeType": "text/plain",
                    "buffer": b"Project Orchid deadline: October 20, 2026.",
                }
            )
            page.locator("#document-authorized").check()
            page.locator("#upload-form button[type=submit]").click()
            expect(page.locator("#document-list")).to_contain_text("orchid.txt")
            page.locator("#document-list").get_by_role("button", name="Summarize / refocus").click()
            page.locator("#detail-dialog").get_by_role("button", name="Summarize locally").click()
            expect(page.locator("#detail-body")).to_contain_text("A grounded local answer.")
            page.locator("#detail-close").click()

            page.locator(".sidebar [data-page=assistant]").click()
            page.locator("#chat-message").fill("When is the Orchid deadline?")
            page.locator("#chat-form button[type=submit]").click()
            expect(page.locator("#chat-log")).to_contain_text("A grounded local answer.")
            expect(page.locator("#chat-log")).to_contain_text("[S1]")

            page.locator(".sidebar [data-page=saved]").click()
            page.locator(".saved-tabs [data-saved-tab=drafts]").click()
            page.locator("#new-draft").click()
            page.locator("#compose-instructions").fill("Ask my advisor for a project review.")
            page.locator("#compose-form button[type=submit]").click()
            expect(page.locator("#draft-body")).to_have_value("A grounded local answer.")
            page.locator("#draft-subject").fill("Orchid review")
            page.locator("#draft-body").fill("My reviewed version.")
            page.locator("#draft-form button[type=submit]").click()
            expect(page.locator("#draft-list")).to_contain_text("My reviewed version.")

            page.locator(".sidebar [data-page=reminders]").click()
            page.locator("#new-reminder").click()
            page.locator("#reminder-title").fill("Prepare capstone slides")
            page.locator("#reminder-due").fill("2026-10-20T09:30")
            page.locator("#reminder-form button[type=submit]").click()
            expect(page.locator("#reminder-list")).to_contain_text("Prepare capstone slides")
            page.locator("#reminder-list").get_by_role("button", name="Mark complete").click()
            expect(page.locator("#reminder-list")).to_contain_text("Completed")

            page.locator(".sidebar [data-page=research]").click()
            page.locator("#research-query").fill("public research topic")
            page.locator("#research-form button[type=submit]").click()
            expect(page.locator("#approval-dialog")).to_be_visible()
            assert search_calls == []
            expect(page.locator("#approval-payload")).to_contain_text("public research topic")
            page.locator("#approval-cancel").click()
            expect(page.locator("#approval-dialog")).not_to_be_visible()
            assert search_calls == []
            page.locator("#research-form button[type=submit]").click()
            page.locator("#approval-confirm").click()
            expect(page.locator("#research-list")).to_contain_text("Synthetic reference")
            assert search_calls == ["public research topic"]

            page.set_viewport_size({"width": 640, "height": 790})
            page.goto(base + "/?desktop=1")
            expect(page.locator("#page-assistant")).to_be_visible()
            expect(page.locator(".sidebar")).not_to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert page.locator("#voice-button").is_hidden()
            before_voice = len(app.state.lumen.model.calls)
            page.locator("#chat-message").fill("Keep my typed text.")
            voice_context = page.evaluate(
                "async () => await window.lumenMac.prepareVoiceCapture('synthetic-voice-1')"
            )
            assert voice_context["mode"] == "ask"
            receipt = page.evaluate(
                "async context => await window.lumenMac.acceptVoiceTranscript("
                "{...context,text:'An explicitly spoken follow-up.'})",
                voice_context,
            )
            assert receipt == {"accepted": True}
            expect(page.locator("#chat-message")).to_have_value(
                "Keep my typed text.\nAn explicitly spoken follow-up."
            )
            assert len(app.state.lumen.model.calls) == before_voice
            replay = page.evaluate(
                "async context => await window.lumenMac.acceptVoiceTranscript("
                "{...context,text:'This must not appear.'})",
                voice_context,
            )
            assert replay["accepted"] is False
            expect(page.locator("#chat-message")).not_to_have_value("This must not appear.")
            voice_context = page.evaluate(
                "async () => await window.lumenMac.prepareVoiceCapture('synthetic-voice-2')"
            )
            page.evaluate("window.lumenMac.cancelVoiceCapture()")
            cancelled = page.evaluate(
                "async context => await window.lumenMac.acceptVoiceTranscript("
                "{...context,text:'Cancelled text must not appear.'})",
                voice_context,
            )
            assert cancelled["accepted"] is False
            assert len(app.state.lumen.model.calls) == before_voice
            voice_context = page.evaluate(
                "async () => await window.lumenMac.prepareVoiceCapture('synthetic-partial')"
            )
            partial = page.evaluate(
                "async context => await window.lumenMac.acceptVoiceTranscript("
                "{...context,text:'Explicitly reviewed partial words.',partial:true})",
                voice_context,
            )
            assert partial["accepted"] is True
            expect(page.locator("#chat-tool-feedback")).to_contain_text("may be incomplete")
            expect(page.locator("#chat-message")).to_have_value(
                "Keep my typed text.\nAn explicitly spoken follow-up.\n"
                "Explicitly reviewed partial words."
            )
            assert len(app.state.lumen.model.calls) == before_voice
            voice_context = page.evaluate(
                "async () => await window.lumenMac.prepareVoiceCapture('synthetic-voice-3')"
            )
            page.locator("#chat-message").fill("x" * 7990)
            too_long = page.evaluate(
                "async context => await window.lumenMac.acceptVoiceTranscript("
                "{...context,text:'This transcript exceeds the combined limit.'})",
                voice_context,
            )
            assert too_long["accepted"] is False
            expect(page.locator("#chat-message")).to_have_value("x" * 7990)
            page.evaluate("window.lumenMac.cancelVoiceCapture()")
            page.locator("#chat-message").fill("")
            for mode in ("note", "reminder", "draft"):
                page.locator(f"[data-chat-mode={mode}]").click()
                voice_context = page.evaluate(
                    "async () => await window.lumenMac.prepareVoiceCapture('synthetic-mode')"
                )
                empty = page.evaluate(
                    "async context => await window.lumenMac.acceptVoiceTranscript("
                    "{...context,text:'   '})",
                    voice_context,
                )
                assert empty["accepted"] is False
                receipt = page.evaluate(
                    "async context => await window.lumenMac.acceptVoiceTranscript("
                    "{...context,text:'Review this synthetic dictation.'})",
                    voice_context,
                )
                assert receipt["accepted"] is True
                expect(page.locator(f"[data-chat-mode={mode}]")).to_have_attribute(
                    "aria-pressed", "true"
                )
                expect(page.locator("#chat-message")).to_have_value(
                    "Review this synthetic dictation."
                )
                page.locator("#chat-message").fill("")
            assert len(app.state.lumen.model.calls) == before_voice
            page.locator("[data-chat-mode=ask]").click()
            voice_context = page.evaluate(
                "async () => await window.lumenMac.prepareVoiceCapture('synthetic-stale')"
            )
            page.locator("#compact-lock").click()
            expect(page.locator("#vault-screen")).to_be_visible()
            page.locator("#passphrase").fill("a browser test passphrase")
            page.locator("#unlock-form button").click()
            expect(page.locator("#workspace")).to_be_visible()
            stale = page.evaluate(
                "async context => await window.lumenMac.acceptVoiceTranscript("
                "{...context,text:'Stale text must not appear.'})",
                voice_context,
            )
            assert stale["accepted"] is False
            expect(page.locator("#chat-message")).to_have_value("")
            held_chat = []
            page.route("**/api/chat", lambda route: held_chat.append(route))
            page.locator("#chat-message").fill("A synthetic pending chat action.")
            page.locator("#chat-submit").click()
            expect(page.locator("#chat-progress")).to_be_visible()
            blocked_voice = page.evaluate(
                "async () => await window.lumenMac.prepareVoiceCapture('busy-blocked')"
            )
            assert "Wait for the current chat action" in blocked_voice["reason"]
            assert len(held_chat) == 1
            held_chat[0].continue_()
            page.unroute("**/api/chat")
            expect(page.locator("#chat-message")).to_have_value("")
            before_notes = len(app.state.lumen.vault.all("note"))
            before_model = len(app.state.lumen.model.calls)
            page.locator("[data-chat-mode=note]").click()
            page.locator("#chat-message").fill("A quick note from chat.")
            assert page.evaluate(
                "window.lumenMac.shareText({text:'Copied text to retain in my note.',mode:'note'})"
            )
            expect(page.locator("[data-chat-mode=note]")).to_have_attribute("aria-pressed", "true")
            page.locator("#chat-submit").click()
            expect(page.locator("#chat-tool-feedback")).to_contain_text(
                "privately, without AI memory"
            )
            assert len(app.state.lumen.vault.all("note")) == before_notes + 1
            assert len(app.state.lumen.model.calls) == before_model
            assert any(
                "Copied text to retain" in item["body"]
                for item in app.state.lumen.vault.all("note")
            )
            expect(page.locator("#shared-text")).to_have_value("")

            page.locator("[data-chat-mode=reminder]").click()
            page.locator("#chat-message").fill("Check the capstone slides.")
            page.locator("#inline-due").fill("2026-10-21T09:30")
            page.locator("#chat-submit").click()
            expect(page.locator("#chat-tool-feedback")).to_contain_text("Check the capstone slides")
            assert len(app.state.lumen.model.calls) == before_model

            page.locator("[data-chat-mode=draft]").click()
            page.locator("#chat-message").fill("Ask my advisor for feedback.")
            page.locator("#share-text").click()
            page.locator("#shared-text").fill(
                "An explicitly shared email asking for a project review."
            )
            page.locator("#chat-submit").click()
            expect(page.locator("#inline-draft-dialog")).to_be_visible()
            blocked_voice = page.evaluate(
                "async () => await window.lumenMac.prepareVoiceCapture('modal-blocked')"
            )
            assert "Close the current review dialog" in blocked_voice["reason"]
            expect(page.locator("#inline-draft-body")).to_have_value("A grounded local answer.")
            assert "project review" in app.state.lumen.model.calls[-1]["data"]["shared_text"]
            page.locator("#inline-draft-subject").fill("Inline reviewed draft")
            page.locator("#inline-draft-body").fill("A reviewed draft from the small window.")
            page.locator("#inline-draft-form button[type=submit]").click()
            expect(page.locator("#chat-tool-feedback")).to_contain_text("Nothing was sent.")
            assert any(
                item["subject"] == "Inline reviewed draft"
                for item in app.state.lumen.vault.all("draft")
            )

            page.locator("[data-chat-mode=ask]").click()
            page.locator("#share-text").click()
            page.locator("#shared-text").fill("A synthetic email asks me to confirm attendance.")
            page.locator("#shared-app").fill("Mail")
            page.locator("#chat-message").fill("Suggest a useful next step.")
            page.locator("#chat-submit").click()
            expect(page.locator("#chat-message")).to_have_value("")
            assert app.state.lumen.model.calls[-1]["data"]["app_name"] == "Mail"
            assert "confirm attendance" in app.state.lumen.model.calls[-1]["data"]["shared_text"]
            expect(page.locator("#chat-log")).to_contain_text("Context you shared for Mail")
            assert page.evaluate("document.getElementById('shared-context').open === false")
            assert page.locator("#chat-log").bounding_box()["height"] >= 200

            before_documents = len(app.state.lumen.vault.all("document"))
            page.locator("#chat-file").set_input_files(
                {
                    "name": "shared-plan.txt",
                    "mimeType": "text/plain",
                    "buffer": b"Project Daisy is due on October 30, 2026.",
                }
            )
            expect(page.locator("#shared-file-consent")).not_to_be_checked()
            assert len(app.state.lumen.vault.all("document")) == before_documents
            page.locator("#shared-file-consent").check()
            page.locator("#chat-message").fill("Suggest how to organize this plan.")
            page.locator("#chat-submit").click()
            expect(page.locator("#chat-message")).to_have_value("")
            assert len(app.state.lumen.vault.all("document")) == before_documents + 1
            assert "Project Daisy" in app.state.lumen.model.calls[-1]["data"]["sources"][0]["text"]
            page.locator("#shared-context > summary").click()
            page.locator("#clear-shared-context").click()
            expect(page.locator("#shared-context")).not_to_be_visible()
            assert len(app.state.lumen.vault.all("document")) == before_documents + 1
            assert page.evaluate(
                "window.lumenMac.shareText('An explicitly shared native selection.')"
            )
            expect(page.locator("#shared-text")).to_have_value(
                "An explicitly shared native selection."
            )
            screenshot_dir = os.getenv("LUMEN_SCREENSHOT_DIR")
            if screenshot_dir:
                page.screenshot(
                    path=str(Path(screenshot_dir) / "lumen-mac-chat.png"), full_page=True
                )
            page.locator("#clear-shared-context").click()
            page.set_viewport_size({"width": 1440, "height": 1050})
            page.goto(base)
            page.locator(".sidebar [data-page=overview]").click()
            expect(page.locator("#recent")).to_contain_text("Orchid travel")
            screenshot_dir = os.getenv("LUMEN_SCREENSHOT_DIR")
            if screenshot_dir:
                page.screenshot(
                    path=str(Path(screenshot_dir) / "lumen-dashboard.png"), full_page=True
                )
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            if screenshot_dir:
                page.screenshot(path=str(Path(screenshot_dir) / "lumen-mobile.png"), full_page=True)

            page.locator(".sidebar [data-page=saved]").click()
            page.locator(".saved-tabs [data-saved-tab=notes]").click()
            page.locator("#note-list article").filter(has_text="Orchid travel").get_by_role(
                "button", name="Delete", exact=True
            ).click()
            expect(page.locator("#approval-dialog")).to_be_visible()
            expect(page.locator("#note-list")).to_contain_text("Orchid travel")
            page.locator("#approval-confirm").click()
            expect(page.locator("#note-list")).not_to_contain_text("Orchid travel")

            page.locator("#lock-button").click()
            expect(page.locator("#vault-screen")).to_be_visible()
            expect(page.locator("#workspace")).not_to_be_visible()
            assert page.locator("#draft-body").input_value() == ""
            assert page.locator("#chat-log").inner_text() == ""
            assert page.evaluate(
                "async () => await window.lumenMac.prepareVoiceCapture('locked-voice')"
            ) is None
            assert errors == []
            assert external == []
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()


def test_mail_import_settings_check_and_candidate_review(tmp_path, monkeypatch):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = create_app(tmp_path, port)
    app.state.lumen.model = FakeModel()

    from lumen import mail

    monkeypatch.setattr(mail, "test_connection", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        mail,
        "fetch_inbox",
        lambda *args, **kwargs: [
            {
                "message_id": "<cedar@example.test>",
                "subject": "Project Cedar",
                "sender": "advisor@example.test",
                "received_at": "2026-12-01T09:00:00+00:00",
                "body": "Project Cedar is due December 12, 2026 at 5pm.",
                "truncated": False,
            }
        ],
    )

    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]})
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        else:
            pytest.fail("Test server did not start.")
        with sync_playwright() as playwright:
            channel = "chrome" if Path("/Applications/Google Chrome.app").exists() else None
            browser = playwright.chromium.launch(channel=channel, headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1050})
            try:
                page.goto(base)
                page.locator("#passphrase").fill("a synthetic mail test passphrase")
                page.locator("#unlock-form button").click()
                expect(page.locator("#workspace")).to_be_visible()

                page.locator(".sidebar [data-page=settings]").click()
                page.locator("#refresh-models").click()
                page.locator("#model-settings-form button[type=submit]").click()
                expect(page.locator("#model-settings-form button[type=submit]")).to_be_enabled()
                page.locator("#mail-username").fill("me@example.test")
                page.locator("#mail-app-password").fill("a synthetic app password")
                page.locator("#mail-settings-form button[type=submit]").click()
                expect(page.locator("#mail-account-status")).to_contain_text("Connected as me@example.test")

                app.state.lumen.model.response = (
                    '[{"message_citation": "M1", "title": "Project Cedar due", '
                    '"due_at": "2026-12-12T17:00:00+00:00", "details": "Reply to advisor."}]'
                )
                page.locator(".sidebar [data-page=saved]").click()
                page.locator(".saved-tabs [data-saved-tab=mail]").click()
                page.locator("#check-mail").click()
                # The result must persist (not only flash in a toast that can be missed).
                expect(page.locator("#mail-check-status")).to_contain_text("Imported 1 message")
                expect(page.locator("#mail-message-list")).to_contain_text("Project Cedar")
                expect(page.locator("#mail-message-list")).to_contain_text("AI access allowed")

                page.locator(".sidebar [data-page=reminders]").click()
                expect(page.locator("#candidate-reminders")).to_be_visible()
                expect(page.locator("#candidate-reminder-list")).to_contain_text("Project Cedar due")
                page.locator("#candidate-reminder-list article").get_by_role(
                    "button", name="Accept", exact=True
                ).click()
                expect(page.locator("#candidate-reminders")).to_be_hidden()
                expect(page.locator("#reminder-list")).to_contain_text("Project Cedar due")

                page.locator(".sidebar [data-page=assistant]").click()
                app.state.lumen.model.response = "Project Cedar is due December 12 [S1]."
                page.locator("#chat-message").fill("When is Project Cedar due?")
                page.locator("#chat-form button[type=submit]").click()
                expect(page.locator("#chat-log")).to_contain_text("December 12")
                expect(page.locator("#chat-log")).to_contain_text("[S1]")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()
