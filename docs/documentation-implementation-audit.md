# Lumen: Documentation and Implementation Audit

Audit date: November 17, 2026.

**November 18 follow-up:** the evaluation portion of G3 now has a versioned 18-case synthetic dataset, opt-in runner, timing/call reports, run-bound human-review forms, and scoring. See the [evaluation guide](evaluation/README.md). Live/human baseline collection remains pending; production observability and the proposed agents/intervention controller remain unimplemented. Findings below retain their original audit dates and context.

**Later November 18 updates:** optional previewed/hash-confirmed [LangSmith export](evaluation/langsmith.md) now supports synthetic evaluation traces/feedback only; no runtime tracing was added. The combined suite passed 139 tests with 2 skipped, using mocked transport rather than a real LangSmith account. A separate [UI inspection and improvement plan](ui-experience-plan.md) records readability/navigation findings and the still-unfixed coupling between settings saves and local-model availability. The README now links a short [everyday user guide](user-guide.md) and states the actual completion status of each main phase.

## Resolution update — November 17, 2026

**A1–A6 are now addressed in source.** The findings, line references, and baseline results below describe the pre-fix snapshot and are retained as audit evidence, not current unresolved defects.

| Finding | Resolution and regression coverage |
|---|---|
| A1 | Live, generation-bound sharing authorization; file-chooser revalidation; single-use delivery receipts. Covered by `tests/test_lifecycle.py`, `tests/test_browser_guards.py`, and fake-provider Swift checks in `tests/test_sharing_native.py`. |
| A2 | Source/session checks before and after every map/reduction call; earlier summaries preserved on failure. Ten regression cases cover both stages and revocation, deletion, edits, locking, and session replacement. |
| A3 | Research finalization uses an encrypted, revision-conditional update that cannot insert a deleted record. Tests exercise normal approved deletion during both successful and failing model calls, plus busy-model evidence retention. |
| A4 | Settings embedding validation, semantic retrieval, and generation share model-work admission control. Tests verify busy rejection and slot release after failure. |
| A5 | Unlock/setup checks validate a saved model without silently replacing it. Browser tests cover stopped Ollama, removed models, and continued note saving. |
| A6 | Repaired the retrieval document's citation example, clarified semantic/keyword behavior, and labeled the model demonstration historical. |

The Swift sources type-check; no installed application bundle has been overwritten. **Rebuild the Mac app to deploy the native sharing changes.** Real clipboard/file chooser behavior remains a manual verification item; automated checks use synthetic providers and do not read personal content. G1–G3 remain proposed work, not implemented or enabled by these fixes. See the [implementation status](implementation-plan.md#implementation-status).

Post-fix validation:

- `LUMEN_BROWSER_TESTS=1 .venv/bin/python -m pytest -q`: **85 passed, 2 skipped**. The skipped checks are the full native-app smoke test and live-model evaluation.
- `.venv/bin/ruff check lumen tests scripts` and `node --check lumen/static/app.js`: passed.
- `xcrun swiftc -typecheck -parse-as-library -swift-version 5 native/Lumen.swift native/VoiceCapture.swift native/LocalVoiceShortcut.swift native/AuthorizedCapture.swift`: passed.
- Local Markdown links across the README and all project docs: valid.

## Summary

The audited application broadly matched the README's bounded, local-first design. The three-agent architecture and several safety controls were **explicit proposals**, not existing features being falsely advertised. The audit found the authorization, lifecycle, coordination, readiness, and documentation gaps recorded below; their resolutions are summarized above.

The remediation and feature-delivery sequence is in [Implementation Plan](implementation-plan.md). The initial audit was documentation-only; its subsequent fixes are tracked separately above.

## Scope and evidence

Reviewed every project-authored Markdown document: `README.md` and the five existing files in `docs/`. Compared them with the Python application, static web interface, Swift sources, installer, retrieval demonstration, and tests. Dependency documentation, caches, generated build outputs, and installed application bundles were not treated as project documentation or verified against source.

Validation performed:

| Check | Result |
|---|---|
| Default test suite: `.venv/bin/python -m pytest -q` | **62 passed, 3 skipped** |
| Isolated headless browser workflow: `LUMEN_BROWSER_TESTS=1 .venv/bin/python -m pytest -q tests/test_browser.py` | **1 passed** |
| `.venv/bin/ruff check lumen tests scripts` | Passed |
| `node --check lumen/static/app.js` | Passed |
| Additional synthetic lifecycle probes | Findings A1–A5 below |

The extra probes used temporary vaults, mocked model/search results, and browser request interception. They did not read a real clipboard, activate a microphone, contact Brave/Ollama, or access personal records. They were one-off audit probes, not new committed regression tests. The full native-app and live-model checks remained unrun; the default suite did run synthetic Swift audio/shortcut checks. No home-lab infrastructure or cluster credentials were accessed.

## Document-by-document comparison

| Document | Comparison with implementation |
|---|---|
| `README.md` | Core workflows, encryption, loopback networking, approvals, retrieval limits, and native speech design are present. Clipboard authorization and saved-model readiness claims need the fixes below. |
| `docs/retrieval-checkpoint.md` | Semantic retrieval exists with the documented batching, similarity floor, and opt-in setting. The citation example is malformed, the floor needs explicit semantic-only scope, and the historical model demonstration was not rerun. |
| `docs/tree-of-thought-assessment.md` | Consistent: no tree-search planner is implemented. Chunk-and-combine summarization is not Tree of Thought. A bounded review loop would not contradict this decision. |
| `docs/multi-agent-architecture.md` | Correctly marked proposed. There are no separate Evidence/Response/Review agents, structured handoff contracts, or bounded review loop yet. |
| `docs/safety-and-intervention-plan.md` | Correctly separates existing safeguards from proposed review, escalation, monitoring, and evaluation targets. Some current safeguards need lifecycle hardening; proposed targets have not been established by the passing tests. |
| `docs/talos-cluster.md` | Explicitly describes a separate home lab, not a Lumen deployment. No Kubernetes deployment assets were found in this project. The October 15 cluster snapshot cannot be verified from application source; this is a verification boundary, not a missing Lumen feature. |

## Findings: authorization and data lifecycle first

### A1 — Sharing uses stale client authorization

**Priority:** P1 — current privacy-boundary gap.

**Evidence:** `README.md:35` promises clipboard reads only while unlocked. `native/Lumen.swift:272–306` checks `window.lumenMac.canShare()` before reading the clipboard. That function returns only the cached `unlocked` flag (`lumen/static/app.js:625–626`); server state is polled every 15 seconds (`app.js:807`). The native file chooser also does not revalidate the session before reading its selected file (`Lumen.swift:310–338`).

**Observed:** with browser requests fully mocked, the session endpoint reported locked while `canShare()` still returned true. The native clipboard-read path was traced statically; no real clipboard was read. A lock or replacement unlock in another session can therefore leave a stale sharing window. Server authentication still protects vault API access; this finding concerns OS content capture before that boundary.

**Required change:** use fresh, session-generation-bound sharing authorization, revalidate after the file chooser, and reject stale delivery. Preserve explicit user initiation; do not introduce clipboard polling. Cross-process authorization remains checkpoint-based, not an absolute guarantee of simultaneous OS/server state.

### A2 — Revoked documents continue into summary reduction calls

**Priority:** P1 — current permission-enforcement hardening.

**Evidence:** `lumen/app.py:459–462` checks document access before map batches, but `app.py:489–505` reduces partial summaries without document checks between calls. The final save is guarded at `app.py:506–508`.

**Observed:** a synthetic six-chunk document made three map calls. Revoking access during the last map call still allowed **three subsequent reduction calls** with derived document content. The endpoint eventually returned 409 and saved no summary.

**Required change:** validate document existence, authorization, revision, and session before and after every map/reduction call. Stop before the next call after a failed checkpoint. The README's narrower final-save guarantee holds; the stronger per-stage safety design is not consistently enforced. Already-issued local inference cannot be recalled.

### A3 — Research completion can undo an approved deletion

**Priority:** P1 — current data-lifecycle defect.

**Evidence:** research evidence is saved before inference (`lumen/app.py:740–747`), making it visible/deletable during generation. Both the error and success paths later write the original result without checking existence/revision (`app.py:757–762`). `lumen/storage.py:75–83` uses an unconditional upsert.

**Observed:** a synthetic research record was deleted through the normal preview/confirm endpoints while its model callback was running. Deletion returned 200 and the record was absent. Generation then returned 200 and **recreated the record**.

**Required change:** make result finalization conditional on the original research record still existing with the expected revision. Apply this to success and error writes. Deletion must win over late completion; do not weaken the existing deletion approval controls.

## Findings: reliability and documentation

### A4 — Settings embedding validation bypasses AI admission control

**Priority:** P2 — current coordination gap.

**Evidence:** generation and semantic chat use `state.ai_lock` (`lumen/app.py:202–213`, `542–550`). Settings calls `state.model.embed()` without that guard (`app.py:649–664`).

**Observed:** with the AI lock already held, a settings update returned 200 and invoked the embedding model. This permits overlap despite the application's existing busy-task behavior and is unsuitable for the proposed serialized workflow.

**Required change:** place inference and embedding validation behind a consistent admission boundary, including settings. Keep lightweight metadata/read-only operations separate from expensive model work where appropriate.

### A5 — Previously configured models bypass readiness checks

**Priority:** P2 — current README/UX mismatch.

**Evidence:** `README.md:31` says an unavailable Ollama/model produces a setup notice. `lumen/static/app.js:119–130` instead hides the notice immediately when a model name is saved, without checking its availability.

**Observed:** with a saved model and a mocked unavailable model-list endpoint, `ensureModel()` made **zero model-list requests** and showed no setup notice. A later AI request still fails explicitly; notes/reminders remain usable.

**Required change:** validate saved-model availability during explicit setup/unlock checks and expose recoverable failure guidance. Do not silently download or replace models, or perform expensive checks on every keystroke.

### A6 — Retrieval document has a broken citation example and ambiguous scope

**Priority:** P3 — documentation correction, not a retrieval-engine defect.

**Evidence:** `docs/retrieval-checkpoint.md:14` begins with `cludes` and illustrates `[S1- pdf1]`, whereas the implemented source label is `[S1]` with title/location stored separately. Its line 20 should explicitly scope the cosine floor to semantic retrieval; keyword retrieval uses overlap ranking and has a documented attachment fallback (`lumen/documents.py:176–225`, `lumen/app.py:557–570`).

**Required change:** repair the sentence/example, clarify semantic versus keyword behavior, and identify the model comparison as a historical demonstration rather than a current benchmark. Do not change working retrieval semantics just to accommodate the malformed example.

## Proposed capabilities not implemented yet

These are delivery gaps against the target design, **not bugs or undisclosed current guarantees**.

| ID | Target | Current implementation and consequence |
|---|---|---|
| G1 | Three roles, typed handoffs, one revision, controller routing | `lumen/app.py` coordinates direct model calls. No role-separated pipeline, review verdict, or simple-versus-complex routing exists. A combined document/research/draft task remains separate user workflows. |
| G2 | Controller-enforced ambiguity, evidence-gap, conflict, and high-impact escalation | `lumen/inference.py:7–15` and task prompts ask for uncertainty/clarification, but there is no structured intervention state or mandatory policy gate. Citation checks at `lumen/app.py:56–66` validate label membership only. |
| G3 | Quality metrics, local stage monitoring, and release gates | Tests use deterministic fakes; the live smoke test and retrieval demo check a few facts. There is no scored evaluation dataset/report, latency distribution, intervention-rate measurement, or per-stage monitoring/release-disable mechanism. The safety plan's 90%/95%/90% targets remain provisional. |

## Confirmed strengths and accepted boundaries

- Encryption, authenticated record identity, restrictive permissions, idle locking, session/CSRF checks, and exact loopback boundaries exist and have relevant tests.
- AI access is opt-in. Chat checks library changes around retrieval/generation and excludes history derived from currently unauthorized sources.
- Search is fixed-destination and approval-gated; the application does not send mail, fetch source pages automatically, or silently use cloud models. Draft saving and record writes remain explicit operations, except documented encrypted conversation/research persistence.
- Full-document summaries cover all chunks structurally, but factual preservation, citation support, and injection resistance are not certified by that coverage or by a review model.
- Parser sandboxing, OS reminder notifications, integrations, autonomous actions, and Kubernetes deployment are explicitly outside current scope. Do not treat their absence as discrepancies requiring implementation.

## Disposition

The original recommendation was to fix **A1–A3 before broadening model workflows**, then address A4–A6 and establish a measured baseline. A1–A6 are now addressed in source with regression tests. Deliver G1–G3 as staged, explicitly enabled features only after establishing evaluation evidence. Passing deterministic checks does not establish the proposed model-quality targets.
