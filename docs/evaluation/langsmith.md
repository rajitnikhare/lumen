# Optional LangSmith export — synthetic evaluations only

Lumen can export **completed synthetic evaluation traces and optional human scores** to an existing private LangSmith tracing project. It is a manual, post-run integration—not production tracing, a cloud inference provider, or a LangSmith-hosted judge. No normal chats, personal vault records, clipboard data, or microphone input are traced.

This uses LangSmith's basic REST API through the existing HTTPX dependency. There is no LangChain/LangSmith SDK requirement, auto-instrumentation, background sender, environment-profile loading, or dependency on LangSmith for local operation. Synchronous, low-volume export is deliberate: it gives a frozen, reviewable payload without affecting measured inference latency.

## Data boundary

An offline preview lists **every request body** that would be sent:

- An evaluation root, case spans, and child generation/embedding spans, using recorded UTC timestamps.
- Synthetic fixture prompts and explicitly shared text, final responses, HTTP/check results, model names, duration/count metadata, and content fingerprints.
- Automatic-check feedback and, only when supplied, known numeric human judgments. Missing judgments are omitted, not uploaded as zeroes.

The export excludes source documents/excerpts, permitted-material snapshots, raw per-call model prompts and outputs, vectors, environment contents, private file paths, reviewer names/notes, and credentials. Model spans therefore show timing/outcome metadata, **not full LLM messages, token usage, or cost estimates**. Reference material remains available in the local review packet.

Synthetic inputs do not guarantee harmless model outputs. **Review final responses and model names in the preview before uploading.** The configured API key is additionally checked against payload values and blocked if present. This is not a general PII detector or anonymization guarantee.

LangSmith receives the selected payload, API credential, and network metadata such as IP address. Its access controls, processing, retention, and billing apply. Feedback requests set `extend_trace_retention=false`, but normal service retention still applies. Uploads cannot be recalled by Lumen, and deleting local files does not delete remote traces. Do not mark the remote project or traces public without a separate review.

## 1. Prepare local results and a private project

Run the [local synthetic evaluator](README.md) with an installed model. Evaluator v1.1.0 and later also write `timings.json`, bound to the exact report. Earlier reports lack recorded span timestamps: keep them local or rerun; this integration does not invent timestamps for old results.

Create/select a **private tracing project** in your LangSmith account and copy its project UUID. If your API key spans multiple workspaces, also supply the workspace UUID. Lumen does not create projects, look up account data, upload datasets, create hosted evaluation experiments, or share traces publicly.

Only these explicitly selected hosted regions are supported:

| CLI region | Fixed API destination |
|---|---|
| `us` (default) | `https://api.smith.langchain.com` |
| `eu` | `https://eu.api.smith.langchain.com` |

Global SDK variables such as `LANGSMITH_TRACING`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`, replica settings, and SDK profiles do not enable or route this exporter. Do not add automatic tracing wrappers to the runtime to bypass this boundary. Other hosting regions or self-hosting require an explicit future configuration change.

## 2. Make an offline preview

Replace `RUN_ID` and `PROJECT_UUID` with your actual run directory and private project UUID:

```sh
.venv/bin/python scripts/evaluate.py langsmith-preview evaluation-results/RUN_ID/report.json --project-id PROJECT_UUID --region us
```

Optional arguments:

- `--reviews evaluation-results/RUN_ID/review-template.json`: attach already-entered human judgments. A reviewer label is required locally, but it and free-text notes are not uploaded. Reviews must match the exact report. Partial known judgments are allowed; unreviewed scores remain absent.
- `--workspace-id WORKSPACE_UUID`: bind the optional tenant-routing header into the preview.
- `--timings PATH`: select the report's matching timing manifest if not beside it.
- `--output PATH`: choose a new preview filename rather than overwrite an existing one.

The command reads no API key and makes no network requests. Inspect the complete `langsmith-preview.json`, including its destination, disclosure, and operation bodies. The command prints a SHA-256 confirmation value for the exact file bytes.

Only reports matching the bundled synthetic dataset and its complete case set are accepted. Simulated test reports are rejected. The exporter checks report/timing/review bindings and recomputes payloads rather than trusting arbitrary JSON operations.

## 3. Explicitly confirm an upload

Supply a LangSmith API key locally, not in chat, source code, a command-line argument, or a committed file. One shell pattern avoids putting the key itself into command history:

```sh
read -s LANGSMITH_API_KEY
LANGSMITH_API_KEY="$LANGSMITH_API_KEY" .venv/bin/python scripts/evaluate.py langsmith-upload evaluation-results/RUN_ID/report.json --preview evaluation-results/RUN_ID/langsmith-preview.json --confirm-sha256 PREVIEW_SHA256
unset LANGSMITH_API_KEY
```

Use the printed fingerprint in place of `PREVIEW_SHA256`. If the preview was made with `--reviews` or a custom `--timings`, provide those same arguments during upload. Do not modify the report, timing manifest, or review form between preview and confirmation. Any change requires a new preview and review.

The uploader verifies the file hash, fixed destination, synthetic dataset, and rebuilt operation list **before reading the credential or making requests**. It then uses only the previewed destination, disables proxy-environment use and redirects, and performs no automatic retries. This does not depend on Ollama availability and does not change local evaluation outcomes or deployment gates.

## Receipts and failures

A private `langsmith-upload-EXPORT_UUID.json` receipt is created beside the report before the first network request. It records attempt/acknowledgment counts and sanitized status codes, never credentials, server response bodies, prompts, or answers. An existing receipt blocks replay of that preview—even if the prior process crashed or the upload was incomplete.

After a timeout, authentication failure, redirect, rate limit, or server error, upload stops. Prior operations may already exist in LangSmith; there is no remote rollback or automatic retry/resume. Local reports and scores remain intact. Inspect the receipt and remote project before deciding whether to create and explicitly approve a new preview. A new preview creates a new trace hierarchy, so retries can otherwise create duplicate snapshots.

The receipt is a local accidental-replay guard, not a cross-machine or adversarial-user authorization service. Copying all artifacts to another directory or machine can bypass local attempt history. API credentials and review confirmation remain explicit user responsibilities.

`complete` means all HTTP requests were acknowledged, not that Lumen independently read back and verified the dashboard. Verify the hierarchy and feedback in your private project. This first integration creates project **traces with feedback**, not LangSmith dataset/experiment comparison tables. No real account upload has been verified during implementation; tests use mocked HTTP transports.

## Timing and interpretation

Case spans use recorded request timestamps; setup failures use their recorded setup spans. Successful-case setup/prelude calls remain separate local metrics rather than children outside the measured request. The evaluation root covers the first-to-last case span, including intervening setup gaps but excluding preflight and the initial setup before the first measured request. Monotonic durations remain available as metadata. Invalid/missing timing bounds are rejected rather than fabricated.

Feedback is descriptive evidence. Automatic passes are not factual accuracy; human judgments are not a guarantee of safety; and a cloud trace does not implement the planned multi-agent review or human-intervention controller. No live/scored baseline or achieved quality target has been established simply by adding this exporter.

## References

- [LangSmith basic tracing API](https://docs.langchain.com/langsmith/trace-with-api)
- [Run/span data format](https://docs.langchain.com/langsmith/run-data-format)
- [Feedback API](https://docs.langchain.com/langsmith/smith-api/feedback/create-feedback)

These public API contracts were reviewed for this integration. The raw HTTP adapter avoids SDK-added runtime/environment metadata and background or replica routing; it trades throughput for explicit payload control. Account configuration, service limits, and future API changes still require real-account verification.
