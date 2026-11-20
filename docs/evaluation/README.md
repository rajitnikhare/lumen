# Synthetic evaluation baseline

Phase 3 now provides evaluation tooling, not an achieved quality score. No live-model baseline or completed human-scored report is checked into this project yet. Runtime observability and multi-agent execution remain separate, planned work. Optional [post-run LangSmith export](langsmith.md) is available for synthetic evaluations only, after offline preview and explicit upload confirmation.

## Scope and privacy

The runner uses only the bundled, versioned `tests/fixtures/evaluation/baseline-v1.json`: 18 synthetic cases. It creates a separate temporary vault for each case and closes/removes it afterward. It has no option to open an existing vault or import arbitrary user files. It does not invoke Brave, fetch websites, activate a microphone, or read the clipboard.

`run` requires explicit `--live` authorization before calling **local Ollama**. It never downloads a model, selects a cloud fallback, or exports to LangSmith. `validate`, `score`, and `langsmith-preview` make no model or network requests. Only `langsmith-upload` can send an explicitly confirmed synthetic export. Production application behavior is unchanged; instrumentation wraps model calls only inside the evaluator.

Unlike production logging, evaluation artifacts intentionally contain **synthetic** requests, shared text, extracted evidence, and responses for review. Output directories use mode `700`, files use `600`, and `evaluation-results/` is ignored by Git. Inspect every artifact before copying it into a public repository. Use a nonidentifying reviewer label and never add real personal details to review notes.

## 1. Validate without inference

Install development dependencies as described in the main README, then run:

```sh
.venv/bin/python scripts/evaluate.py validate
```

This checks the schema, document/fact references, duplicate identifiers, provenance declaration, and fixture size limits. It prints the dataset version, case count, and SHA-256 without contacting Ollama. Dataset provenance is a curation commitment, not an automatic detector of private information; keep this fixture synthetic.

## 2. Run an explicitly selected local model

Use the exact name of an installed local completion model. The following names are examples, not models the runner will install:

```sh
# Keyword-retrieval baseline.
.venv/bin/python scripts/evaluate.py run --live --model llama3:latest

# A separate run with optional semantic retrieval.
.venv/bin/python scripts/evaluate.py run --live --model llama3:latest --embedding-model nomic-embed-text
```

The suite includes a multi-call long-document summary and can be slow on a laptop. Local-model requests retain Lumen's normal context/output limits and timeouts. Do not equate one small suite with statistical validation. Repeat experiments, record hardware separately without identifying details, and use held-out cases before making broader claims.

Every run creates a new random directory under `evaluation-results/` (or `--output-dir`). Existing files are never overwritten:

| Artifact | Purpose |
|---|---|
| `report.json` | Per-case response, permitted evidence, checks, request/setup timing, and measured model calls. Also includes dataset hash, source fingerprints, dependency versions, model names, and before/after model digests. |
| `timings.json` | Recorded UTC case/model-call spans, bound to the exact report. Used for optional post-run trace export; not fabricated from duration estimates. |
| `operational-metrics.json` | Case-check counts, per-workflow median/p95 timing, generation/embedding counts, and expected-document recall. |
| `summary.md` | Compact automated results; explicitly marks quality review pending. |
| `review-packet.md` | Requests, reference facts, responses, and evidence, with model/source text fenced as untrusted quotations. |
| `review-template.json` | Run-bound human-review form; judgments start as `null`, never automatic passes. |

Missing/changing model digests or changed evaluation sources prevent a clean eligibility check. Before/after snapshots do not prove that a mutable model tag was unchanged at every instant. Keep the environment stable while running.

Hashes of application, inference, retrieval, and storage source identify the prompt/policy/retrieval implementation used in the run; evaluator and CLI source are fingerprinted too. They are content fingerprints rather than manually assigned prompt release tags.

## 3. Complete human review and score

Read the [scoring rubric](rubric.md), the review packet, and the original response/evidence. Edit `review-template.json`, supply a nonidentifying `reviewer`, and fill applicable fields. Do not edit `report.json`; a canonical report fingerprint binds the review to its actual outputs.

Replace `RUN_ID` below with the printed run directory:

```sh
.venv/bin/python scripts/evaluate.py score evaluation-results/RUN_ID/report.json --reviews evaluation-results/RUN_ID/review-template.json
```

This produces `scored-report.json` and `scored-report.md`. To revise a review and score again, choose a new `--output` filename. A blocked or incomplete score exits with status 1; invalid input or an output collision exits with status 2. `run` returns 1 for failed automatic checks or unverifiable source/model snapshots, while still retaining the run's artifacts.

`provisional_targets_met` means only that this reviewed run met the documented development criteria. It never changes application settings, enables agents, or certifies a deployment. An unreviewed, failed, or simulated run cannot earn that status. The scorer rejects mismatched dataset versions/hashes, changed reports, missing/duplicate case reviews, impossible claim counts, and inconsistent automatic checks.

## What is measured

### Automated observations—not factual accuracy

- Exact expected HTTP status, including expected 400/422 input rejections. An outcome named `request_failed` can therefore be an expected rejection whose checks pass.
- Nonempty responses, unauthorized-source identifiers, forbidden synthetic canaries in measured model inputs/answers, and inference avoidance for invalid inputs.
- Request wall time and generation/embedding call durations/counts. Request timing excludes vault/model setup; setup time and calls are reported separately. Metadata-listing requests are not inference calls. Preflight embedding validation is recorded separately in model identity metadata.
- Per-workflow median and nearest-rank p95. These contain successful and failed measured requests, so inspect case outcomes rather than interpreting them as a success-only latency SLA.
- Expected-document recall: expected relevant document IDs found in workflow sources divided by all expected relevant IDs, per workflow. This is not chunk recall, citation support, or a calibrated confidence measure.

The invalid-input inference check applies to the submitted request after setup. If semantic retrieval is enabled, model-configuration validation can still make a separately reported setup embedding call.

Revocation/deletion cases first make an authorized prelude request, then change access through the normal API and enable history on the measured follow-up. Only follow-up model inputs are subject to the forbidden-canary checks; setup/prelude calls are recorded separately. Existing regression tests remain necessary for races, approvals, encryption, and fail-safe behavior not exhaustively represented by these fixtures.

### Human judgments

The scorer reports correctness, supported personal-fact claims, summary fact coverage, appropriate abstention, unnecessary abstention/escalation, high-impact review guidance, and critical errors. It publishes denominators and review coverage. Missing judgments produce `null` metric values rather than fabricated scores; no-claim and no-sample ratios remain undefined.

Provisional targets remain correctness ≥90%, groundedness ≥95%, and appropriate abstention ≥90%. Automatic failures, identified critical errors, incomplete review, missing identity evidence, or failed high-impact review guidance block the development gate. The high-impact score judges the response's guidance, **not an implemented human-intervention controller**.

The dataset is intentionally small and fixed-order. Temperature, model implementation, hardware, and cache/warmup state can change answers and latency. Source fingerprints make the procedure attributable; they do not guarantee identical outputs. Keep version 1 immutable once collecting baseline results; a revised benchmark needs a new version and matching runner/dataset evidence for later rescoring.

## Tests and current status

```sh
.venv/bin/python -m pytest -q tests/test_evaluation.py
```

These tests use fake models and handcrafted scoring examples to verify isolation, counting, validation, artifact handling, and scoring math. They are **not live-model quality or performance results**. Simulated evaluator reports suppress human quality metrics and are ineligible for the development gate.

Recorded tooling-validation results are in [validation.md](validation.md); they are not a measured model-quality baseline.

Next acceptance step: explicitly run the selected real local model, complete human review, and retain a scored single-agent baseline before beginning Phase 4 experiments. The earlier capstone report is dated November 17 and correctly describes the pre-evaluator snapshot; it should be refreshed with real results only after that step.
