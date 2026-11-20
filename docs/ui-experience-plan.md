# Lumen: Simpler UI Experience Plan

Date: November 18, 2026. **Status: UI-1, UI-2, and UI-3 are implemented. UI-4 (human usability testing) remains proposed.**

## Goal

Make everyday work obvious without making Lumen more autonomous. The interface should help a new user ask, save a note, set an exact reminder, or prepare a draft without learning retrieval terminology or navigating developer settings. Preserve explicit AI access, reviewed writes, and external-request approvals.

Chat is already the landing page. The improvement is a clearer task flow, not another home/dashboard screen or a framework migration. Prioritize the compact Mac-sized view while sharing patterns with the browser interface.

## Evidence from the current interface

Inspection used a temporary synthetic vault, mocked inference, and headless browser screenshots at 640×790 and 1440×1000. No personal records, clipboard, microphone, live model, or external research were used. This is an expert inspection, not a completed human usability study or full accessibility certification.

| Finding | Original evidence | Status |
|---|---|---|
| Dense composer with weak visual hierarchy | At 640×790, the composer was 314px high, with nine visible buttons across the screen. Compact mode chips, history labels, and disclosure text were 10px. | **Partly addressed:** text sizes and spacing improved (below). The composer still shows every sharing control at once; a labeled Create/Attach grouping remains an open follow-up. |
| Small, muted controls | Muted text `#7b8580` on white was 3.81:1; unselected mode text `#7a897d` on `#fafbf9` was 3.55:1; text buttons `#608370` on white were 4.22:1. These fell below the normal-text 4.5:1 AA target. | **Implemented:** these and related low-contrast colors (navigation, empty states, permission pills, danger buttons, breadcrumb, notices) were darkened to at least 4.5:1 against their actual backgrounds, and most reading text grew from 10–12px to 12–14px. |
| Empty space without a useful first step | The empty chat area said "A calm place to think" but provided no actionable example. | **Implemented:** the empty chat state now shows three buttons — Ask a question, Save a note, Set a reminder — that switch the composer's mode and focus it, without submitting anything or changing permissions. |
| Navigation hides structure or exposes too much | Compact mode has an eight-view dropdown; the wide browser exposes many separate destinations. | **Implemented:** navigation is now My day / Assistant / Saved / Reminders / Research, with Settings and Lock in a separate sidebar-bottom group. Documents, Notes, Email drafts, and Mail are tabs inside Saved. |
| Forms dominate saved content | The Notes screen opens with a large blank editor; the saved list begins near the fold. Drafts show generation and editing forms simultaneously. | **Implemented:** saved views are list-first with a toolbar search box; the New/Add/Edit forms are hidden until an explicit New/Edit/Add action, with their own Cancel/Close buttons. |
| Setup mixes beginner and advanced concepts | Chat model, embedding model, and Brave credentials share one long settings form. | **Implemented:** Settings is split into four independent forms — Local AI model, Optional document search, Optional web research, and Optional mail import — each with its own save button. |
| Context and storage states are hard to distinguish | Shared text can remain in collapsed details after Ask; removing an attachment leaves its authorized library copy. | **Still proposed.** No change was made to this behavior or its labeling. |
| Errors and readiness lack actionable continuity | Many failures are temporary toasts; the "ON DEVICE" badge is not a live readiness indicator. | **Still proposed.** Toasts remain the only failure surface; no persistent inline error area or saved-item receipt link was added. |

### Backend coupling exposed by the UI review — fixed

`PUT /api/settings` previously validated the model even when the only requested change was removing the Brave key. A synthetic outage probe returned HTTP 502 and the encrypted saved key remained present.

**This is now fixed in source.** `save_settings` only calls `state.model.models()` when the requested model differs from the stored one, and only calls `state.model.embed()` when the requested embedding model differs and is non-empty. Brave-key-only and other non-model changes no longer contact Ollama. After any validation, the handler re-reads current settings before merging omitted fields, so a concurrent change is not silently overwritten. Regression tests (`tests/test_app.py::test_removing_brave_key_does_not_require_ollama` and `test_changing_model_still_validates_it_against_ollama`) cover both the fixed and the still-required-check paths.

The [user guide](user-guide.md) and README have been updated to remove the stale limitation notice.

## Proposed interaction model

- **Chat:** readable conversation, one obvious composer, contextual attachment chips, visible current action, optional Create menu, and a concise local-AI status.
- **Saved:** documents, notes, and drafts as tabs within one searchable library. Use clear “Saved privately” versus “Available to local AI” badges.
- **Reminders:** upcoming/completed lists and an exact date/time editor. Continue to state that these are in-app reminders, not OS notifications.
- **Settings:** short, independently saved sections with step-by-step recovery when a model is unavailable. Raw model names and embedding details remain available under advanced controls.

Privacy explanations should be understandable and placed at the point of consequence. Move repeated background explanations into help panels, but never hide required consent, exact external queries, persistent storage implications, or destructive-action approvals.

## Implementation sequence

### UI-1 — Readability and everyday chat (implemented)

**Touchpoints:** `lumen/static/index.html`, `chat.css`, `style.css`, `app.js`, and browser tests.

- Improved typography, contrast, and spacing without changing permissions or endpoints: the muted/nav/button/empty-state/pill/notice colors were darkened to at least 4.5:1 against their actual backgrounds, and most small reading text grew to 12–14px.
- Added an actionable empty chat state (Ask a question / Save a note / Set a reminder) that switches the composer's mode and focuses it.
- Verified at 640×790 (compact) and 1440×1000 (browser) with headless screenshots and computed-style checks; no horizontal overflow was observed.

**Not done in this pass:** consolidating the sharing controls into a labeled Attach/Create area, persistent inline error surfaces, a saved-item success link, and a live local-AI readiness indicator beyond the existing setup notice. These remain open UI-1/UI-2 follow-ups.

**Acceptance:** `LUMEN_BROWSER_TESTS=1 pytest -q` passed (141 passed, 2 skipped) after these changes, confirming no regression to existing workflows. A full 200%-zoom and keyboard-only pass across 450×560/390×844 has not been separately recorded.

### UI-2 — List-first saved work and simpler navigation (implemented)

**Touchpoints:** `lumen/static/index.html`, `app.js`, `style.css`, and browser tests.

- Documents, notes, and drafts are grouped under one **Saved** page with tabs (`.saved-tabs`, reusing the existing `.tool-chip` styling), each with its own search box.
- A fourth tab, **Mail**, was added as part of the later read-only Gmail import feature; it follows the same list-first/search/authorize/revoke/delete pattern as Documents.
- New/Add/Edit forms (`#upload-form`, `#note-form`, `#draft-editor`, `#reminder-form`) are hidden by default and opened only by an explicit New/Add/Edit action (`showPanel`/`hidePanel` helpers), each with its own Cancel/Close button. Editing/Cancel always resets the form through the existing pure field-populator functions (`editNote`/`editDraft`/`editReminder`); panel visibility is handled separately at each call site.
- Search filters operate only on already-decrypted, in-memory unlocked data and are cleared on lock (`showVault()` resets all search inputs and hides all panels).

**Acceptance:** `LUMEN_BROWSER_TESTS=1 pytest -q` passes with updated workflow tests that open hidden forms explicitly before filling fields, confirming equivalent functionality rather than just new selectors.

### UI-3 — Guided setup and independently saved settings (implemented)

- **Backend coupling fixed:** `PUT /api/settings` only contacts Ollama when the chat or embedding model actually changes, re-reads current settings before merging omitted fields, and is covered by regression tests for both the Brave-key-only and model-changed paths.
- **UI split implemented:** Settings is now four independent forms — `#model-settings-form`, `#embedding-settings-form`, `#research-settings-form`, and `#mail-settings-form` — each with its own submit button, so saving one does not require re-submitting unrelated fields. Forms other than the model form send a client-side guard error ("Select and save a local AI model first.") if no model is selected yet, since the backend's `model` field is always required.
- **Still proposed:** a capability-aware model-list API for a better embedding picker (the current chat-model list excludes embedding-only models), and a live readiness indicator beyond the existing setup notice.

**Acceptance:** offline notes/reminders still work; credential removal succeeds during a mocked Ollama outage (`test_removing_brave_key_does_not_require_ollama`); a changed model is still validated and rejected on a mocked outage (`test_changing_model_still_validates_it_against_ollama`); model errors do not erase or falsely acknowledge settings changes. No credentials enter UI logs or telemetry. A race between the navigation-triggered settings reload and an in-flight form submission was found and fixed by scoping the reload's busy-state to the whole settings page (`run($("page-settings"), ...)`), covered by the full settings browser test.

### UI-4 — Validate the experience before adding more controls

- Conduct short human sessions with synthetic tasks: first note, document Q&A permission, an exact reminder, and recovery from offline AI.
- Measure task completion, time, wrong turns, and whether users understand AI access, storage, and external approval. These are future measurements, not achieved usability results.
- Check screen-reader names, dialog focus/return, keyboard navigation, error announcements, contrast, and zoom/reflow. Existing browser checks are a starting point, not a WCAG audit.

## Features that need separate design, not just new buttons

- **New chat:** current conversation history is one stored collection. Real independent conversations require backend thread/history scoping. Do not label a hidden old transcript as a fresh private thread.
- **Stop:** aborting a browser request is not proof that Ollama stopped. Define cancellation/checkpoint/persistence behavior before claiming a task is cancelled.
- **Progress stages:** add actual backend stage reporting before showing retrieval/review progress. The proposed Review Agent is not implemented.
- **Rich answer formatting:** use a strictly sanitized subset if Markdown is added; never render raw model HTML or weaken CSP.
- **Automatic actions:** easier UI must not turn model text into silent note/reminder writes, guessed dates, external searches, or sends.

## Relationship to the main implementation plan

The existing safety fixes and evaluation tooling are useful foundations, but do not complete the proposed multi-agent, intervention, or production-monitoring phases. UI-1, UI-2, and UI-3 are implemented; UI-4 (human usability testing) remains proposed and should happen before adding further controls. LangSmith remains synthetic-evaluation-only, not an excuse to send daily-use analytics to the cloud.
