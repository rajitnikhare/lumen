# Evaluation-tooling validation — November 18, 2026

This is a **software validation artifact**, not a live-model evaluation or a scored baseline. All evaluator tests use fake models or handcrafted review examples. No actual model-quality metric is claimed here.

## Dataset

- ID: `lumen-synthetic-baseline`
- Version: `1.0.0`
- Cases: **18**
- Source: `tests/fixtures/evaluation/baseline-v1.json`
- SHA-256: `e920dc26de8099e6d3dc1b010080c7a4f1eb71746e15039f76475df3c3235e55`

## Recorded checks

| Command/check | Result |
|---|---|
| `.venv/bin/python scripts/evaluate.py validate` | 18 synthetic cases validated; no model/network calls. |
| `.venv/bin/python -m pytest -q tests/test_evaluation.py` | 29 passed. |
| LangSmith adapter checks (included in the combined suite) | 25 passed using mocked HTTP transport; no real account upload. |
| `LUMEN_BROWSER_TESTS=1 .venv/bin/python -m pytest -q` | 139 passed, 2 skipped after the synthetic-only LangSmith integration. |
| `.venv/bin/ruff check lumen tests scripts` | Passed. |
| `node --check lumen/static/app.js` | Passed. |
| Local Markdown links | Validated. |

The two skipped checks were the existing full native-app smoke test and live-model smoke test. Automated validation did not read a personal vault, real clipboard, microphone, or live search service. Fixed-loopback model metadata behavior was tested with mocked HTTP transport. The opt-in evaluator itself was not run against real Ollama.

LangSmith tests additionally verify offline preview, exact hash/payload confirmation, allowlisted destinations, metadata minimization, credential exclusion, one-attempt receipts, no redirects/retries, sanitized partial failures, and optional human feedback without unknown values becoming zeroes. Real account/project/dashboard verification remains pending. Recorded timing manifests are tested separately from duration-only reports, and normal evaluation commands remain local even when SDK tracing environment variables are set.

## What the evaluator tests establish

- All 18 fixture scenarios execute through the real application API with synthetic backends and isolated temporary vaults.
- Generation/embedding and setup/request accounting are separated, including the authorized prelude in history-revocation/deletion cases.
- Errors, canary violations, and changed source snapshots are observable; failures are not dropped from reports.
- Review files are tied to the exact report/dataset, and automatic checks cannot be removed or overridden by positive human ratings.
- Missing human judgments remain unknown; simulated reports cannot become model-quality measurements.
- Handcrafted examples verify metric denominators, claim weighting, summary omissions, failure accounting, and nearest-rank p95 calculations.
- Artifacts are private by default, output collisions are rejected, and untrusted model text cannot escape its review-packet Markdown fence.

## Remaining acceptance evidence

A real, explicitly selected local-model run and completed human review are still required. Capture the model digests, source/dataset fingerprints, per-case results, reviewer judgments, and scored report from that run. Refresh this artifact after relevant code changes; do not treat these development test counts as factual accuracy, safety certification, or proof that the provisional 90%/95%/90% quality targets were reached.
