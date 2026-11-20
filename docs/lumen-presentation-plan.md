# Lumen: 8–10-Minute Capstone Presentation Plan

Target duration: **9 minutes**. Audience: technical reviewers. This is a presentation outline based on the supplied directions, not a completed video or an unseen presentation template. **Revised November 19, 2026** to account for work completed after the initial draft (Phase 3 evaluation tooling, the LangSmith synthetic export, a three-part UI revision, and an optional read-only Gmail import capability); see the matching revision note in `lumen-capstone-report.md`.

## Core message

Lumen combines local inference, an encrypted permission-aware library, and explicit user control. Its strongest demonstrated result is tested workflow behavior—not a claim of autonomous factual correctness. The presentation should tell the same story as `lumen-capstone-report.md` and distinguish current implementation from proposed agents and safety extensions.

## Timed outline

| Time | Slide or demonstration | Key message and evidence |
|---|---|---|
| 0:00–0:45 | 1. Problem and intended user | Personal information is fragmented; a general model lacks private facts. Introduce a Mac user who wants help without automatically uploading a library. Avoid claiming measured productivity gains. |
| 0:45–1:30 | 2. Scope and deliberate boundaries | Documents, notes, drafts, exact reminders, approved public research, and optional read-only Gmail import. Emphasize no email sending, app control, silent clipboard collection, always-listening mode, or background mail sync — every external action is explicit and reviewed. |
| 1:30–2:45 | 3. Implemented architecture | Walk through interface → session/permission controller → encrypted library → authorized retrieval → local Ollama → citation/lifecycle checks. Explain separate approval-gated Brave access and the separate explicit "Check for new mail" → read-only IMAP → candidate-reminder review path. Label this the current architecture, not a three-agent runtime. |
| 2:45–3:45 | 4. Design evolution | Explain explicit memory, keyword-to-optional-semantic retrieval, rejection of unnecessary Tree of Thought, audit-driven hardening, and the later UI consolidation/mail-import additions that kept the same permission philosophy. Confirm the exact Module 1–6 chronology from original submissions before assigning module labels. |
| 3:45–5:45 | 5. Synthetic workflow demonstration | Show authorized document Q&A, the source, revocation, and an explicitly saved note/reminder. Explain that source-label checks are not factual verification. Demonstrate an approval preview and/or a mail-import check (with a prepared synthetic test mailbox) only if time permits; neither real external call is necessary to make the core point. |
| 5:45–7:00 | 6. Evaluation and safety evidence | Show the recorded 165 passed / 2 skipped test result and one lifecycle regression. Mention the separate synthetic scored-evaluation harness (18 cases, rubric) exists but has no live human-scored baseline yet — do not present it as a quality result. Explain that skipped native/live-model checks limit the claim. Highlight deletion-safe completion and per-stage revocation checks. |
| 7:00–8:15 | 7. Limitations and next steps | Two-excerpt Q&A, repeated embeddings, extraction limits, possible hallucinations, and mail import's bounded 90-day/200-message window with best-effort date extraction requiring explicit review. Proposed next step: run the existing scored harness against a real model with human review, then an opt-in Evidence/Response/Review workflow with one revision. Do not present either as a completed result. |
| 8:15–9:00 | 8. Conclusion and repository | Summarize the trade-off: less autonomy, more inspectability and control. Show the verified public repository URL once available and point to reproducible synthetic tests. |

Total: **9:00**. Rehearse with transitions included. Keep a 30–60-second buffer for model latency or shorten the live demonstration if needed.

## Demonstration preparation

Use a completely separate temporary vault and synthetic files. Never open a real personal vault on camera. Hide desktop notifications, unrelated tabs, personal paths, account details, and any source material that is not safe to publish. Do not display API keys, even briefly.

Suggested synthetic document:

> Project Cedar's final submission deadline is December 12, 2026. The presentation is in Room Willow. The materials budget is USD 300.

Suggested flow:

1. Import `synthetic-project-guide.txt` without AI access. Explain the difference between storage permission and AI permission.
2. Authorize the file and ask: “What is Project Cedar's final submission deadline?” Show the retrieved source and inspect its text. Model wording may vary; do not promise a successful answer without rehearsal.
3. Revoke AI access and repeat with recent conversation enabled. Explain that the source and derived history should be excluded. If the model still invents the fact, show this as a quality failure rather than editing it into a success.
4. Save a synthetic note or an exact reminder using explicit controls. Point out that these writes do not require model inference.
5. Optionally show an external-search preview and cancel it. A synthetic key is not a functioning search credential; use a prepared, clearly labeled mock if demonstrating approval without a real configured service.
6. Optionally show the Mail tab: a prepared synthetic test mailbox (never a real personal account) with "Check for new mail" producing an imported message and a candidate reminder, then accept or discard it. Narrate that this is read-only, explicit-trigger-only, and that nothing becomes a reminder without that explicit step. Skip this step entirely if short on time; it is not required to demonstrate the core permission model.

Use `scripts/demo_retrieval.py` only if you explicitly choose to run the installed local models. It creates a temporary vault. The historical USD 47 comparison in the report is not evidence that a fresh recording will produce identical wording or scores.

## Evidence and fallback strategy

- Record a clean, synthetic demonstration in advance if live-model latency makes the presentation unreliable. Label prerecorded or mocked segments accurately.
- Use a captured test output or results file from an actual run; include the command and date. The last recorded combined suite was `LUMEN_BROWSER_TESTS=1 .venv/bin/python -m pytest -q`: 165 passed, 2 skipped on November 19, 2026 (up from 85 passed on November 17, reflecting evaluation tooling, UI, and mail-import work added since).
- State that the skipped checks were the full native-app and live-model smoke checks. Synthetic Swift tests and source type-checking do not prove microphone accuracy. Separately, mail import has only been verified against a fake IMAP double in tests, not a real Gmail account — say so if asked.
- Show architecture diagrams as implemented versus proposed. Do not portray the 90%/95%/90% quality targets as measured outcomes, even though a scored-evaluation harness now exists to measure them.
- If a step fails, explain the observed error and safety behavior. Never describe a tool action as completed without its actual result.

## Final deliverable checklist

- [ ] Confirm the original Module 1–6 chronology and adjust the design-evolution narrative without inventing milestones.
- [ ] Review the report draft, including limitations and the distinction between deterministic tests and real-model quality.
- [ ] Add and verify a public GitHub URL; curate source and documentation before publishing.
- [ ] Remove or sanitize private infrastructure information, local paths, vaults, credentials, personal records, logs, recordings, and generated artifacts. Review any commit history as well.
- [ ] Include setup instructions, dependency configuration, main code, synthetic examples, tests, and an evaluation artifact in the public repository.
- [ ] Rebuild the native app if using the latest sharing fixes, then verify the actual installed application with nonsensitive material.
- [ ] If demonstrating mail import live, use a dedicated synthetic/test mailbox and an app password created only for that purpose — never a real personal inbox — and revoke/delete the app password afterward if it is not needed again.
- [ ] Rehearse the full presentation to 8–10 minutes, including transitions and demonstration time.
- [ ] Confirm that every screenshot, recording, and example is public, synthetic, or properly anonymized.
- [ ] Ensure that the final report, repository, and video make consistent implementation and evaluation claims.
