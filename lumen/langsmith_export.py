"""Explicit, post-run exports of bundled synthetic evaluations; never runtime tracing."""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4, uuid5

import httpx
from pydantic import Field, field_validator, model_validator

from lumen.evaluation import EvaluationInput
from lumen.evaluation_scoring import operational_summary, report_digest, score_report, validate_run

ENDPOINTS = {"us": "https://api.smith.langchain.com", "eu": "https://eu.api.smith.langchain.com"}
DISCLOSURE = (
    "Upload only this frozen synthetic evaluation export to LangSmith. It includes synthetic "
    "case prompts/shared text, final responses, timings, model names, checks, fingerprints, "
    "and optional numeric human scores. It excludes vaults, source documents/excerpts, API keys, "
    "reviewer names/notes, environment contents, and per-call model payloads. LangSmith receives "
    "your credential and network metadata; its retention, terms, and billing apply. Review "
    "model outputs too: synthetic inputs do not guarantee nonsensitive outputs. Uploads cannot "
    "be recalled, and interrupted uploads may already have reached the service."
)
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024


def moment(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Trace timestamps must include a timezone.")
    return parsed.astimezone(UTC)


class SpanTiming(EvaluationInput):
    started_at: str = Field(max_length=80)
    ended_at: str = Field(max_length=80)

    @model_validator(mode="after")
    def ordered(self):
        if moment(self.ended_at) < moment(self.started_at):
            raise ValueError("A trace cannot finish before it starts.")
        return self


class CallTiming(SpanTiming):
    operation: Literal["generate", "embed"]


class CaseTiming(SpanTiming):
    phase: Literal["request", "setup"]
    calls: list[CallTiming]


class TimingManifest(EvaluationInput):
    schema_version: Literal[1] = 1
    run_id: str
    report_sha256: str
    cases: dict[str, CaseTiming]


class ExportDestination(EvaluationInput):
    endpoint: Literal["https://api.smith.langchain.com", "https://eu.api.smith.langchain.com"]
    project_id: str
    workspace_id: str | None = None

    @field_validator("project_id", "workspace_id")
    @classmethod
    def canonical_uuid(cls, value):
        return str(UUID(value)) if value is not None else None


class ExportOperation(EvaluationInput):
    path: Literal["/runs", "/feedback"]
    body: dict


class ExportPreview(EvaluationInput):
    schema_version: Literal[1] = 1
    export_id: str
    created_at: str
    disclosure: str = DISCLOSURE
    destination: ExportDestination
    report_sha256: str
    timing_sha256: str
    reviews_sha256: str | None
    operations: list[ExportOperation] = Field(min_length=1, max_length=4000)

    @field_validator("export_id")
    @classmethod
    def canonical_uuid(cls, value):
        return str(UUID(value))


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def read_artifact(path: Path):
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("Evaluation artifact exceeds the 16 MiB export limit.")
    raw = path.read_bytes()
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise ValueError("Evaluation artifact exceeds the 16 MiB export limit.")
    return raw


def validate_timings(report, timings):
    if timings.run_id != report.run_id or timings.report_sha256 != report_digest(report):
        raise ValueError("Timings belong to a different or changed report.")
    if set(timings.cases) != {result.case_id for result in report.results}:
        raise ValueError("Timings must contain every evaluation case exactly once.")
    for result in report.results:
        timing = timings.cases[result.case_id]
        phase = "setup" if result.outcome == "setup_failed" else "request"
        calls = result.setup_calls if phase == "setup" else result.calls
        if timing.phase != phase or len(timing.calls) != len(calls):
            raise ValueError(f"Timing/model-call mismatch: {result.case_id}")
        for call, span in zip(calls, timing.calls, strict=True):
            if call.operation != span.operation or not (
                moment(timing.started_at) <= moment(span.started_at)
                <= moment(span.ended_at) <= moment(timing.ended_at)
            ):
                raise ValueError(f"Model span is inconsistent with its case: {result.case_id}")


def run_operation(identifier, name, timing, destination, *, inputs, outputs,
                  metadata, parent=None, run_type="chain", error=None):
    body = {
        "id": identifier, "name": name, "run_type": run_type,
        "session_id": destination.project_id,
        "start_time": timing.started_at, "end_time": timing.ended_at,
        "inputs": inputs, "outputs": outputs, "extra": {"metadata": metadata},
        "tags": ["lumen", "synthetic-evaluation"],
    }
    if parent is not None:
        body["parent_run_id"] = parent
    if error is not None:
        body["error"] = error
    return ExportOperation(path="/runs", body=body)


def feedback_operation(export_id, run_id, destination, key, score, *, human=False):
    return ExportOperation(path="/feedback", body={
        "id": str(uuid5(UUID(export_id), f"feedback:{run_id}:{key}")),
        "run_id": run_id, "session_id": destination.project_id,
        "key": key, "score": round(float(score), 4), "extend_trace_retention": False,
        "feedback_source": {"type": "api" if human else "auto_eval",
                            "metadata": {"origin": "human_review" if human else "automatic_check"}},
    })


def root_operation(report, dataset, timings, destination, export_id, has_reviews):
    spans = list(timings.cases.values())
    timing = SpanTiming(
        started_at=min(moment(span.started_at) for span in spans).isoformat(),
        ended_at=max(moment(span.ended_at) for span in spans).isoformat(),
    )
    operations = operational_summary(report, dataset)
    metadata = {
        "evaluation_run_id": report.run_id, "dataset_sha256": report.dataset_sha256,
        "report_sha256": report_digest(report), "evaluator_version": report.evaluator_version,
        "model": report.model, "embedding_model": report.embedding_model,
        "code_sha256": digest(report.source_fingerprints), "sources_unchanged": report.sources_unchanged,
        "model_identity_sha256": digest(report.model_identity),
        "model_identity_verified": report.model_identity.get("verified") is True,
        "human_review_attached": has_reviews, "scope": "bundled_synthetic_only",
        "timing_scope": "first_to_last_case_span; preflight_and_initial_setup_excluded",
    }
    return run_operation(
        export_id, "Lumen synthetic evaluation", timing, destination,
        inputs={"dataset": dataset.dataset_id, "version": dataset.version},
        outputs={"case_count": operations["case_count"],
                 "automatic_case_passes": operations["automatic_case_passes"]},
        metadata=metadata,
        error="Automatic evaluation checks failed." if operations["automatic_failures"] else None,
    )


def case_operations(report, case, result, timing, destination, export_id):
    case_id = str(uuid5(UUID(export_id), case.id))
    operations = [run_operation(
        case_id, f"Synthetic case: {case.id}", timing, destination, parent=export_id,
        inputs={"prompt": case.prompt, "shared_text": case.shared_text},
        outputs={"response": result.response, "http_status": result.http_status,
                 "checks": result.checks, "source_count": len(result.sources)},
        metadata={"case_id": case.id, "workflow": case.workflow, "phase": timing.phase,
                  "request_duration_ms": result.duration_ms, "setup_duration_ms": result.setup_duration_ms},
        error="Automatic evaluation checks failed." if not all(result.checks.values()) else None,
    )]
    calls = result.setup_calls if timing.phase == "setup" else result.calls
    for index, (call, span) in enumerate(zip(calls, timing.calls, strict=True)):
        operations.append(run_operation(
            str(uuid5(UUID(case_id), f"call:{index}")), f"Local {call.operation}", span, destination,
            parent=case_id, run_type="llm" if call.operation == "generate" else "embedding",
            inputs={"operation": call.operation, "model_payloads_captured": False},
            outputs={"succeeded": call.succeeded, "input_canary_violations": len(call.input_violations)},
            metadata={"ls_provider": "ollama", "duration_ms": call.duration_ms,
                      "ls_model_name": report.model if call.operation == "generate" else report.embedding_model},
            error=None if call.succeeded else "Local model call failed.",
        ))
    operations.append(feedback_operation(
        export_id, case_id, destination, "lumen.automatic_checks_passed", all(result.checks.values()),
    ))
    return operations


def human_case_feedback(case, result, review):
    values = {}
    if result.http_status != 200 or case.expected_behavior == "reject":
        return values
    for name in ("answer_correct", "abstained", "escalated"):
        value = getattr(review, name)
        if value is not None:
            values[name] = value
    if review.personal_claims and review.supported_personal_claims is not None:
        values["groundedness"] = review.supported_personal_claims / review.personal_claims
    if case.workflow == "summary" and review.covered_fact_ids is not None and case.reference_facts:
        values["summary_coverage"] = len(review.covered_fact_ids) / len(case.reference_facts)
    if review.critical_errors is not None:
        values["no_critical_errors"] = review.critical_errors == 0
    return values


def review_operations(report, dataset, dataset_sha256, reviews, destination, export_id):
    if not reviews.reviewer.strip():
        raise ValueError("Supply a reviewer label before exporting human feedback; the label is not uploaded.")
    scored = score_report(report, dataset, dataset_sha256, reviews)
    operations = []
    for key, metric in scored["human_metrics"].items():
        if metric.get("value") is not None:
            operations.append(feedback_operation(
                export_id, export_id, destination, f"lumen.human.{key}", metric["value"], human=True,
            ))
    cases = {case.id: case for case in dataset.cases}
    results = {result.case_id: result for result in report.results}
    for review in reviews.reviews:
        case_id = str(uuid5(UUID(export_id), review.case_id))
        values = human_case_feedback(cases[review.case_id], results[review.case_id], review)
        operations.extend(feedback_operation(
            export_id, case_id, destination, f"lumen.human.{key}", value, human=True,
        ) for key, value in values.items())
    return operations


def make_preview(report, dataset, dataset_sha256, timings, destination, *, reviews=None,
                 export_id=None, created_at=None):
    validate_run(report, dataset, dataset_sha256)
    if report.mode != "live":
        raise ValueError("Only live synthetic evaluation reports may be exported, not simulated test runs.")
    validate_timings(report, timings)
    export_id = str(UUID(export_id)) if export_id else str(uuid4())
    created_at = created_at or datetime.now(UTC).isoformat()
    moment(created_at)
    operations = [root_operation(report, dataset, timings, destination, export_id, reviews is not None)]
    results = {result.case_id: result for result in report.results}
    for case in dataset.cases:
        operations.extend(case_operations(
            report, case, results[case.id], timings.cases[case.id], destination, export_id,
        ))
    automatic = operational_summary(report, dataset)
    operations.append(feedback_operation(
        export_id, export_id, destination, "lumen.automatic_case_pass_rate",
        automatic["automatic_case_passes"] / automatic["case_count"],
    ))
    if reviews is not None:
        operations.extend(review_operations(report, dataset, dataset_sha256, reviews, destination, export_id))
    return ExportPreview(
        export_id=export_id, created_at=created_at, destination=destination,
        report_sha256=report_digest(report), timing_sha256=digest(timings.model_dump()),
        reviews_sha256=digest(reviews.model_dump()) if reviews is not None else None,
        operations=operations,
    )


def write_receipt(handle, receipt):
    handle.seek(0)
    json.dump(receipt, handle, indent=2)
    handle.write("\n")
    handle.truncate()
    handle.flush()
    os.fsync(handle.fileno())


def contains_credential(value, credential):
    if isinstance(value, str):
        return credential in value
    if isinstance(value, dict):
        return any(contains_credential(key, credential) or contains_credential(item, credential)
                   for key, item in value.items())
    if isinstance(value, list):
        return any(contains_credential(item, credential) for item in value)
    return False


def upload_operations(preview, receipt_path, api_key):
    if not api_key or len(api_key) > 4096 or not all(33 <= ord(char) <= 126 for char in api_key):
        raise ValueError("Set a valid LANGSMITH_API_KEY for this explicit upload command.")
    if contains_credential(preview.model_dump(), api_key):
        raise ValueError("The configured credential appears in the export. Upload was blocked.")
    receipt = {"export_id": preview.export_id, "status": "in_progress",
               "started_at": datetime.now(UTC).isoformat(), "attempted": 0, "acknowledged": 0,
               "error_code": None, "total_operations": len(preview.operations)}
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    if preview.destination.workspace_id:
        headers["X-Tenant-Id"] = preview.destination.workspace_id
    with receipt_path.open("x+", encoding="utf-8") as handle:
        receipt_path.chmod(0o600)
        write_receipt(handle, receipt)
        transport = httpx.HTTPTransport(retries=0, trust_env=False)
        with httpx.Client(timeout=15, trust_env=False, follow_redirects=False, transport=transport) as client:
            for operation in preview.operations:
                receipt["attempted"] += 1
                write_receipt(handle, receipt)
                try:
                    response = client.post(preview.destination.endpoint + operation.path,
                                           headers=headers, json=operation.body)
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    receipt["status"] = "incomplete"
                    receipt["error_code"] = (
                        f"http_{exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError)
                        else "network_error"
                    )
                    break
                receipt["acknowledged"] += 1
                write_receipt(handle, receipt)
            else:
                receipt["status"] = "complete"
        receipt["ended_at"] = datetime.now(UTC).isoformat()
        write_receipt(handle, receipt)
    return receipt
