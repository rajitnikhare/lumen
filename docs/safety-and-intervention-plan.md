# Lumen: Safety and Human Intervention Plan

## 1. Purpose and relevant risks

My capstone project, **Lumen**, is a local-first assistant for document Q&A, summaries, notes, reminders, message drafts, and explicitly approved public research. It provides bounded assistance, not autonomous computer control. The [proposed multi-agent architecture](multi-agent-architecture.md) separates Evidence, Response, and Review agents under a deterministic controller.

Risks include unsupported answers, incorrect dates or amounts, misleading summaries, privacy disclosures, and prompt injection. Retrieval can select irrelevant passages; valid citations may not support claims. Handoffs can lose qualifications, and agents sharing a model may repeat mistakes. Ambiguity and tool failures can cause incorrect actions or false completion claims.

**Status:** encryption, permission checks, approval gates, and bounded local inference already exist. Multi-agent review, formal evaluation targets, risk-based escalation, and expanded monitoring below are proposed controls, not demonstrated guarantees.

## 2. Guardrails and constrained behavior

- **Validate inputs:** retain file-type, upload-size, extraction, and context limits. Require explicit timezone-aware reminder dates. Reject unreadable files; disclose extraction omissions and unsandboxed parsing. Sensitive-identifier query checks never replace user review.
- **Enforce least privilege:** only authorized documents and notes enter retrieval. The controller mediates tools; agents cannot grant permissions, send mail, execute commands, or control applications. The Review Agent receives only the request, permitted evidence, and candidate answer. Personal data stays with loopback Ollama; there is no cloud-model fallback.
- **Constrain outputs and sources:** retain source labels and inspectable excerpts, reject invented citation IDs, and distinguish personal evidence from general knowledge. The proposed reviewer checks claim support and missing qualifications. Source text is untrusted data, never authority to change permissions. Prompt instructions and model review reduce risk but cannot guarantee injection resistance or factual accuracy.
- **Require approval for impact:** retain frozen, expiring, single-use approvals for external queries and revision-bound deletion. Preview sends nothing externally. Notes, reminders, and draft saves use explicit controls; completed chat turns persist as encrypted history. Email sending remains unavailable, even with approval.
- **Fail safely at runtime:** recheck sessions, permissions, and revisions at workflow checkpoints. Reject affected results after locking or revocation; reject truncated output rather than saving apparent success. The proposed workflow permits one revision and final review, then stops. Monitor stage status, duration, and failure category without plaintext prompt logging. Never silently retry an uncertain external request or substitute another retrieval method.

## 3. Evaluation metrics and acceptance criteria

Evaluation would use synthetic documents, known facts, unanswerable questions, conflicting evidence, injection attempts, malformed files, and simulated failures. Human scoring assesses quality separately from deterministic security tests. Targets below are proposed, not measured results.

| Metric | Measurement and initial criterion |
|---|---|
| Answer correctness | At least 90% of answerable cases meet a predefined human-scored factual rubric; separately report critical date/amount errors. |
| Groundedness and coverage | At least 95% of checkable personal-fact claims are supported by supplied evidence; separately score required-fact omissions in summaries. Citation existence alone does not count. |
| Appropriate abstention | At least 90% of unsupported or conflicting cases lead to clarification or qualified abstention. Also report unnecessary abstentions on answerable cases. |
| Permission and approval compliance | Zero unauthorized records in intercepted model payloads and zero unapproved external calls or deletions in the test suite. Any violation blocks release. |
| Failure handling | Every injected lock, revocation, timeout, invalid-citation, and truncation case follows its defined safe outcome; none is reported as successful completion. |
| Oversight and efficiency | Report escalation rate, human-rated unnecessary escalations, median/p95 latency, and model-call count by task type against the single-agent baseline. |

Retrieval similarity and self-reported confidence are not calibrated probabilities. Escalation depends on evidence gaps, conflicts, risk, and validation—not confidence alone. Targets require review before deployment; passing tests does not prove universal safety.

## 4. When human intervention is required

The controller would pause for human input when:

1. **Intent is ambiguous:** the requested record, recipient, date, timezone, or desired outcome is unclear. Ask a focused question rather than infer consequential details.
2. **Evidence is insufficient or conflicting:** sources are missing, inconsistent, potentially stale for the question, or review still finds unsupported claims after one revision. Show the limitation and request clarification or additional authorized material.
3. **Privacy or action impact increases:** require explicit authorization for AI access and exact-query or deletion approval. Additional access needs fresh consent; agent agreement never supplies it.
4. **Consequences are high:** flag legal, medical, financial, or consequential deadline advice for source inspection and qualified human review before reliance. Do not autonomously act on it.
5. **Execution state is unsafe:** stop on session changes, permission changes, repeated failures, or uncertain external delivery. Require renewed authorization where applicable; never offer an override that bypasses security checks.

## 5. Integrated strategy and dependable deployment

The plan applies **defense in depth, least privilege, fail-safe defaults, human-in-the-loop oversight, and continuous evaluation**. Guardrails restrict available actions; evaluation tests their effectiveness; escalation handles uncertainty that automated checks cannot resolve. Review-agent approval never overrides controller policy or user consent.

Review increases latency, and frequent confirmation risks approval fatigue. Multi-agent processing targets evidence-heavy tasks; additional intervention targets ambiguity or consequence without removing mandatory approvals. Clear disclosures support informed consent.

Deployment would remain single-user and local-first, starting with synthetic testing and an opt-in pilot. Re-run permission, injection, and quality evaluations after model or workflow changes; disable the affected AI workflow when safety regressions occur. Local monitoring avoids external telemetry. Encryption protects data at rest, not an unlocked or compromised device; trusted files, FileVault, private backups, and OS updates remain necessary. This supports cautious real-world use without claiming autonomous correctness or production certification.
