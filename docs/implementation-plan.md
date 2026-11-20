# Lumen: Documentation Alignment and Implementation Plan

Created: November 17, 2026.

Status as of November 18, 2026: **Phases 0–2 implemented; Phase 3 tooling implemented with live/human baseline collection pending; Phases 4–6 remain planned.** This plan follows the [documentation/implementation audit](documentation-implementation-audit.md). Finding IDs below refer to that audit's pre-fix snapshot.

## Implementation status

| Phase | Status |
|---|---|
| 0 — Documentation baseline | Complete: repaired retrieval wording and linked current behavior to explicitly proposed designs. |
| 1 — Authorization and lifecycle | Implemented with API, storage, browser, and fake-provider Swift regression tests. Native sources type-check; deployment requires rebuilding the Mac app. Real OS sharing remains a manual check, not an automated guarantee. |
| 2 — Admission and readiness | Implemented with busy-task, failure-release, and saved-model readiness regression tests. |
| 3 — Scored evaluation baseline | Tooling implemented: 18-case versioned synthetic dataset, opt-in local runner, timing manifests/call counts, source/model fingerprints, human-review packet/form, rubric, and scoring. Optional confirmed LangSmith export is limited to these synthetic evaluations. Explicit live runs and completed human review are still required to establish the baseline. |
| 4 — Bounded multi-agent orchestration | Not started; no new agent workflow has been enabled. |
| 5 — Human-intervention outcomes | Not started; current deterministic approvals and model-prompted uncertainty remain distinct from the proposed policy controller. |
| 6 — Monitoring and rollout gates | Production monitoring remains unimplemented; no runtime tracing or automatic fallback was added. Optional post-run LangSmith export for synthetic evaluations is a separate Phase 3 extension, not app telemetry. |
| UI-1/UI-2/UI-3 (parallel UX track) | Implemented: readability/contrast fixes, an actionable empty-chat state, the settings/Ollama coupling fix, a consolidated list-first Saved page (Documents/Notes/Drafts/Mail tabs), and Settings split into four independently saved forms (model/embedding/research/mail). UI-4 (human usability testing) remains proposed. See the [UI experience plan](ui-experience-plan.md). |

The remaining sections retain each phase's scope and acceptance criteria. A1–A6 are resolved in source. The measurement portion of G3 now has tooling, not measured quality results; G1, G2, and production monitoring remain proposed.

**Parallel proposed UX track:** the [UI experience plan](ui-experience-plan.md) records a synthetic-screen inspection and a phased readability/navigation/setup redesign. It also identifies the remaining settings coupling that blocks Brave-key removal during a local-model outage. No frontend redesign or settings-decoupling fix is claimed as implemented yet. Everyday instructions for the current interface are in the [user guide](user-guide.md).

## Objective and boundaries

First close current authorization, lifecycle, and reliability defects. Then implement the submitted multi-agent and safety designs incrementally, with evaluation demonstrating whether additional model calls are worthwhile.

Preserve local-only inference, per-record authorization, explicit writes, exact-query approvals, single-use revision-bound deletion, no mailbox sending, and no autonomous OS/app control. Do not add cloud fallback, automatic external queries, clipboard polling, a vector database, Tree of Thought, or a Kubernetes deployment as incidental work.

Priorities: **P1** protects authorization/deletion semantics; **P2** addresses reliability or proposed feature delivery; **P3** corrects documentation. Phases contain independently reviewable work and acceptance checks rather than speculative time estimates.

## Phase 0 — Establish an accurate documentation baseline

**Addresses:** A6 and cross-document status clarity. No dependency.

- Repair the citation example and incomplete sentence in `docs/retrieval-checkpoint.md`; distinguish semantic thresholds from keyword ranking/fallback.
- Keep `README.md` as the current-behavior guide. Link it to proposed architecture/safety documents and clearly label planned versus implemented controls.
- Keep the Talos document a dated, separate infrastructure runbook; do not represent its cluster state as newly verified.
- Record command results, model identity, and verification limits with later evaluation reports. Do not carry historical demonstration claims forward as fresh measurements.

**Done when:** document claims map to code/tests or are explicitly marked planned/unverified, links resolve, and citation examples match actual labels. Existing working retrieval behavior is unchanged.

## Phase 1 — Close current safety and lifecycle gaps

**Addresses:** A1–A3. Highest implementation priority; required before Phase 4 rollout.

### 1A. Session-bound clipboard and file sharing

**Touchpoints:** `lumen/app.py`, `lumen/static/app.js`, `native/Lumen.swift`, `tests/test_app.py`, `tests/test_browser.py`, and focused native sharing tests.

- Add a live, session-generation-bound sharing authorization flow, following the existing voice authorization pattern without granting model access automatically.
- Replace the synchronous cached `canShare()` decision for OS reads with an awaited server check. Revalidate after file selection and before content delivery; discard stale-session results.
- Keep clipboard/file access behind explicit user actions. Treat lock notifications as helpful signals, not authorization proofs.
- Design tests around injected fake clipboard/file providers so locked-session tests never read personal content or request OS permissions.

**Acceptance:** a server lock or replacement unlock before sharing authorization prevents capture; locking while a chooser is open prevents the subsequent file read; stale delivery is rejected. Test provider call counts as well as UI state. Document checkpoint limitations rather than promising atomic cross-process cancellation.

### 1B. Permission checks across every summary stage

**Touchpoints:** `lumen/app.py:summarize`, `tests/test_app.py`.

- Capture the session and source revision for the workflow.
- Recheck existence, authorization, revision, and session before and after each map/reduction call and before persistence.
- Preserve an existing saved summary if the new workflow fails. Stop further model work after an invalidation checkpoint; do not claim to recall a request already issued.

**Acceptance:** inject revocation, source deletion/edit, lock, and session replacement during map and reduction stages. No subsequent model call occurs after detection, no new summary is saved, and the user receives an explicit failure/cancellation outcome. Reproduce the audit's six-chunk case as a permanent regression test.

### 1C. Deletion-safe research finalization

**Touchpoints:** `lumen/app.py:confirm_approval`, conditional record updates in `lumen/storage.py` if needed, `tests/test_app.py`, `tests/test_storage.py`.

- Finalize only an existing research record with its expected revision; never upsert a deleted result during late success or failure handling.
- Represent incomplete model work consistently, including busy-task failures rather than leaving ambiguous `retrieved` states without a reason. Do not write after a lock or resurrect deleted records to record an error.
- Preserve already-retrieved evidence when allowed, without automatically reissuing the approved search.

**Acceptance:** delete through normal approval endpoints while research inference is suspended. Resume with both success and model error: the record remains absent and completion is not reported as success. Test busy inference, timeouts, locking, and one-use search approvals separately.

## Phase 2 — Make model admission and setup behavior consistent

**Addresses:** A4–A5. Coordinate admission changes with Phase 1; complete before multi-agent execution.

**Touchpoints:** `lumen/app.py:AppState.generate`, semantic retrieval and settings validation, `lumen/static/app.js:ensureModel`, `tests/test_app.py`, `tests/test_browser.py`.

- Apply one consistent admission policy to generation, retrieval embeddings, and settings embedding validation. Choose explicit busy rejection rather than an unbounded queue; avoid nested-lock deadlocks.
- Keep metadata listing distinct from expensive model work. Prevent mid-workflow configuration changes from silently changing the selected model by capturing or validating workflow configuration.
- Check a previously configured chat model during unlock/setup. Surface stopped Ollama, removed models, and recoverable setup errors while leaving notes/reminders available.
- Keep availability distinct from quality: installed does not imply accurate, and no model should be silently downloaded or substituted.

**Acceptance:** a held model-work slot prevents settings from invoking embeddings; overlapping requests fail predictably; the slot releases on every failure/cancellation. Saved-model outages show actionable setup guidance, with no background download or uncontrolled polling.

## Phase 3 — Build the evaluation baseline before adding agents

**Addresses:** measurement portion of G3. Depends on current-behavior fixes for a meaningful baseline.

**Implemented assets:** `tests/fixtures/evaluation/baseline-v1.json`, `scripts/evaluate.py`, `lumen/evaluation.py`, `lumen/evaluation_scoring.py`, `tests/test_evaluation.py`, and [evaluation documentation](evaluation/README.md).

- Create versioned synthetic cases covering answerable/unanswerable questions, paraphrases, unrelated passages, conflicting/stale evidence, summaries, shared context, prompt injection, high-impact questions, and malformed input.
- Separate deterministic permission/failure tests from opt-in real-model evaluation. Use unique synthetic secrets to inspect model payloads before/after revocation, deletion, and session changes.
- Define the human-scoring rubric and denominators for answer correctness, claim support, summary omissions, abstention, and unnecessary escalation before scoring.
- Report sample counts, critical date/amount errors, median/p95 latency, model calls, model/embedding names, and prompt/policy versions. Retain evaluation outputs only for synthetic cases unless the user explicitly authorizes otherwise.
- Treat the safety document's correctness ≥90%, groundedness ≥95%, and appropriate-abstention ≥90% as provisional targets. Any tested authorization/approval violation blocks release regardless of average quality. Do not infer confidence from retrieval similarity.

**Acceptance:** an opt-in command produces a reproducible report with both automated measurements and clearly identified human scores. A single-agent baseline exists; mocked text generation is never counted as measured model accuracy.

**Remaining acceptance step:** explicitly run the selected real local model and complete the bound human-review form. The runner/scorer and their failure paths are tested with fakes and handcrafted examples only. Do not mark the baseline achieved or begin default multi-agent rollout based on those tests.

**Optional export:** [LangSmith integration](evaluation/langsmith.md) supports offline preview and hash-confirmed upload of synthetic-only traces/feedback to an existing private project. Local evaluation remains independent of this service. Real LangSmith account/dashboard verification remains a manual setup step; tests use mocked transports.

## Phase 4 — Deliver bounded multi-agent orchestration

**Addresses:** G1. Depends on Phases 1–3. Initially opt-in and limited to evidence-heavy chat.

**Suggested additions:** `lumen/workflows.py` for coordination and `lumen/agents.py` for the three bounded roles. Extend `lumen/app.py`, `lumen/inference.py`, and tests rather than introducing an agent framework or distributed services.

- Define validated handoffs for the task, permitted evidence/revisions, candidate response, and review findings. Carry session/configuration snapshots and provenance through the whole workflow.
- Implement Evidence → Response → Review with at most one Response revision and one final review. Reject malformed or policy-invalid handoffs; no agent receives raw vault/tool authority.
- Keep simple questions on the existing response path and note/reminder/draft saving deterministic. Use explicit routing rules before considering model-based routing.
- Handle insufficient evidence and context-budget failures explicitly. Review receives the permitted evidence needed for its judgment; do not silently truncate it and claim full review.
- Keep research separately user-approved. Connecting approved snippets to a combined workflow must not generate/send a personal query automatically or reuse an approval.
- Preserve chunk-and-combine for full-document summaries. Extend review to summaries, research comparison, and drafting only after their context budgets and tests are defined.

**Acceptance:** mocked tests establish stage order, bounded call counts, handoff validation, cancellation, source-revision checks, and denied tool escalation. Compare opt-in real-model quality and latency with Phase 3. Do not enable by default without a demonstrated benefit at an acceptable local cost.

## Phase 5 — Enforce human-intervention outcomes

**Addresses:** G2. Define policy alongside Phase 4; enable with tested workflow outcomes.

**Suggested addition:** `lumen/safety.py`; update API responses, `lumen/static/app.js`, and `lumen/static/index.html`.

- Define controller-owned outcomes such as answered, needs clarification, needs human review, failed, and cancelled; distinguish these from mandatory approval challenges.
- Require clarification for consequential missing inputs and source conflicts; request additional authorized evidence rather than granting access.
- Establish a conservative high-impact policy for legal/medical/financial guidance and consequential deadlines. Provide source inspection and qualified-human-review guidance, acknowledging that automatic classification can miss cases.
- Let review findings trigger escalation, but never let model confidence or agent agreement override permissions, approvals, or unsupported-claim checks.
- Make the UI explain what is missing and what action the user can take. No insecure “continue anyway” control and no UI claim that Lumen verified a conclusion merely because a reviewer accepted it.

**Acceptance:** policy fixtures verify missing inputs, evidence gaps/conflicts, persistent review failures, and high-impact categories. Browser tests verify that escalation cannot be mistaken for completed work, silently saved as a validated answer, or used to bypass required approval.

## Phase 6 — Add privacy-preserving monitoring and rollout gates

**Addresses:** operational portion of G3. Instrument earlier phases as useful; final rollout depends on all applicable acceptance checks.

- Record bounded local stage metadata: random task ID, workflow/stage, duration, call count, outcome, and sanitized failure/escalation category. Avoid raw prompts, source text, personal queries, credentials, and document titles in logs.
- Prefer in-memory metrics; if history is retained, define retention and use the encrypted vault. Add no external telemetry.
- Expose a clear way to disable the new AI workflow while preserving deterministic notes/reminders. Make fallback to the baseline explicit, user-selected, and subject to the same safety gates—not an automatic bypass after review failure.
- Gate rollout on security regressions, measured quality, and reviewed latency budgets. Re-evaluate after model/prompt/policy changes and disable affected AI workflows on regressions.
- Finish with the full default suite, isolated browser checks, opt-in live-model evaluation, and explicit native/manual sharing and speech checks. Do not activate microphones, read real clipboard content, modify login settings, or access cluster infrastructure as part of unattended validation.

**Acceptance:** report generation reveals no plaintext sensitive content; disabling the new workflow works; evaluation history distinguishes model versions and runs. Native/on-device speech and real hardware behavior are recorded as manually verified or explicitly unverified, never inferred from mocks.

## Delivery order and completion definition

Recommended sequence: **documentation corrections → P1 boundary/lifecycle fixes → admission/readiness fixes → scored baseline → bounded agents and intervention policy → measured rollout**.

Update this plan and the audit's status as each item lands. A feature is complete only when its code, failure-path tests, user-visible behavior, documentation, and applicable evaluation evidence agree. The plan does not require implementing the README's explicitly deferred integrations or deploying Lumen to the home-lab cluster.
