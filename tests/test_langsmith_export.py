import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from lumen.evaluation import (
    CaseResult,
    EvaluationReport,
    ModelCall,
    automatic_checks,
    load_dataset,
)
from lumen.evaluation_scoring import report_digest, review_template
from lumen.langsmith_export import (
    ENDPOINTS,
    ExportDestination,
    TimingManifest,
    make_preview,
    upload_operations,
)
from scripts import evaluate

PROJECT_ID = "11111111-1111-4111-8111-111111111111"
WORKSPACE_ID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def artifacts(tmp_path):
    dataset, checksum = load_dataset()
    results = []
    timings = {}
    base = datetime(2026, 11, 18, tzinfo=UTC)
    for index, case in enumerate(dataset.cases):
        started = base + timedelta(seconds=index * 2)
        has_call = case.expected_status == 200
        calls = [ModelCall(operation="generate", duration_ms=100.0, succeeded=True)] if has_call else []
        response = "Synthetic adapter test output, not a measured model result."
        results.append(CaseResult(
            case_id=case.id, outcome="completed" if has_call else "request_failed",
            http_status=case.expected_status, response=response, duration_ms=1000.0,
            setup_duration_ms=1.0, calls=calls, setup_calls=[],
            checks=automatic_checks(case, case.expected_status, response, calls, []),
            retrieved_documents=[], sources=[{"text": "SOURCE-SENTINEL"}],
            permitted_material=[{"text": "DOCUMENT-SENTINEL"}],
        ))
        timings[case.id] = {
            "phase": "request", "started_at": started.isoformat(),
            "ended_at": (started + timedelta(seconds=1)).isoformat(),
            "calls": [{"operation": "generate", "started_at": (started + timedelta(milliseconds=100)).isoformat(),
                       "ended_at": (started + timedelta(milliseconds=200)).isoformat()}] if has_call else [],
        }
    report = EvaluationReport(
        run_id="synthetic-export-unit-test", created_at=base.isoformat(), mode="live",
        dataset_id=dataset.dataset_id, dataset_version=dataset.version, dataset_sha256=checksum,
        evaluator_version="test", model="test-local:latest", embedding_model="",
        model_identity={"verified": True, "not_exported": "IDENTITY-SENTINEL"},
        source_fingerprints={"/not-a-real-user/path": "PATH-SENTINEL"}, sources_unchanged=True,
        environment={"not_exported": "ENVIRONMENT-SENTINEL"}, results=results,
    )
    manifest = TimingManifest(run_id=report.run_id, report_sha256=report_digest(report), cases=timings)
    evaluate.write_json(tmp_path / "report.json", report.model_dump())
    evaluate.write_json(tmp_path / "timings.json", manifest.model_dump())
    return SimpleNamespace(dataset=dataset, checksum=checksum, report=report,
                           timings=manifest, directory=tmp_path)


def preview_for(artifacts, **kwargs):
    destination = ExportDestination(endpoint=ENDPOINTS["us"], project_id=PROJECT_ID,
                                    workspace_id=WORKSPACE_ID)
    return make_preview(artifacts.report, artifacts.dataset, artifacts.checksum,
                        artifacts.timings, destination, **kwargs)


def install_transport(monkeypatch, handler):
    from lumen import langsmith_export

    original = httpx.Client

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        kwargs.pop("transport").close()
        return original(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(langsmith_export.httpx, "Client", client)


def test_preview_is_hierarchical_and_excludes_sensitive_metadata(artifacts):
    preview = preview_for(artifacts)
    runs = [operation.body for operation in preview.operations if operation.path == "/runs"]
    root = runs[0]
    assert root["id"] == preview.export_id
    assert all(run["session_id"] == PROJECT_ID for run in runs)
    by_id = {run["id"]: run for run in runs}
    for run in runs:
        UUID(run["id"])
        assert run["start_time"] <= run["end_time"]
        if run is not root:
            assert run["parent_run_id"] in by_id
    assert sum(run["run_type"] == "llm" for run in runs) == 16
    payload = json.dumps([operation.model_dump() for operation in preview.operations])
    for sentinel in ("SOURCE-SENTINEL", "DOCUMENT-SENTINEL", "IDENTITY-SENTINEL",
                     "PATH-SENTINEL", "ENVIRONMENT-SENTINEL", "LUMEN_EVAL_DENIED_91"):
        assert sentinel not in payload
    assert "What is Project Cedar" in payload
    assert all(operation.body["extend_trace_retention"] is False
               for operation in preview.operations if operation.path == "/feedback")


def test_human_feedback_omits_unknowns_and_reviewer_information(artifacts):
    reviews = review_template(artifacts.report)
    reviews.reviewer = "REVIEWER-SENTINEL"
    reviews.reviews[0].notes = "NOTES-SENTINEL"
    preview = preview_for(artifacts, reviews=reviews)
    assert not any(operation.body.get("feedback_source", {}).get("type") == "api"
                   for operation in preview.operations)
    review = reviews.reviews[0]
    review.answer_correct = False
    review.personal_claims = 2
    review.supported_personal_claims = 1
    review.abstained = False
    review.escalated = False
    review.critical_errors = 0
    preview = preview_for(artifacts, reviews=reviews)
    feedback = {operation.body["key"]: operation.body["score"] for operation in preview.operations
                if operation.path == "/feedback" and operation.body["feedback_source"]["type"] == "api"}
    assert feedback["lumen.human.answer_correct"] == 0.0
    assert feedback["lumen.human.groundedness"] == 0.5
    assert "lumen.human.answer_correctness" not in feedback
    serialized = preview.model_dump_json()
    assert "REVIEWER-SENTINEL" not in serialized
    assert "NOTES-SENTINEL" not in serialized


@pytest.mark.parametrize("change", ["dataset", "mode", "report", "timing", "call", "timezone"])
def test_preview_rejects_unbound_or_invalid_data(artifacts, change):
    if change == "dataset":
        artifacts.checksum = "wrong-dataset"
    elif change == "mode":
        artifacts.report.mode = "simulated"
    elif change == "report":
        artifacts.report.results[0].response = "Changed after timings were recorded"
    elif change == "timing":
        artifacts.timings.cases.pop("deadline")
    elif change == "call":
        artifacts.timings.cases["deadline"].calls = []
    else:
        artifacts.timings.cases["deadline"].started_at = "2026-11-18T00:00:00"
    with pytest.raises(ValueError):
        preview_for(artifacts)


@pytest.mark.parametrize("endpoint", ["http://api.smith.langchain.com", "https://attacker.invalid", "https://api.smith.langchain.com/redirect"])
def test_only_allowlisted_https_destinations_are_supported(endpoint):
    with pytest.raises(ValidationError):
        ExportDestination(endpoint=endpoint, project_id=PROJECT_ID)


def test_preview_ignores_global_tracing_configuration_and_reads_no_credentials(artifacts, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Offline preview attempted a network request or read a credential")

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://attacker.invalid")
    monkeypatch.setenv("LANGSMITH_RUNS_ENDPOINTS", '{"https://attacker.invalid":"fake"}')
    monkeypatch.setattr(evaluate, "os", SimpleNamespace(environ=SimpleNamespace(get=forbidden)))
    monkeypatch.setattr(httpx, "Client", forbidden)
    assert evaluate.main(["validate"]) == 0
    assert evaluate.main(["langsmith-preview", str(artifacts.directory / "report.json"),
                          "--project-id", PROJECT_ID]) == 0
    assert "No request was sent and no credential was read" in capsys.readouterr().out
    path = artifacts.directory / "langsmith-preview.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text())["destination"]["endpoint"] == ENDPOINTS["us"]


def upload_arguments(artifacts, path):
    return ["langsmith-upload", str(artifacts.directory / "report.json"),
            "--preview", str(path), "--confirm-sha256", hashlib.sha256(path.read_bytes()).hexdigest()]


@pytest.mark.parametrize("change", ["confirmation", "payload", "destination", "report", "timings"])
def test_upload_requires_exact_confirmation_and_rebuilt_payload(artifacts, monkeypatch, change):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid export attempted a network request or read a credential")

    path = artifacts.directory / "preview.json"
    data = preview_for(artifacts).model_dump()
    if change == "payload":
        data["operations"][0]["body"]["inputs"]["unexpected"] = "MUST NOT BE SENT"
    if change == "destination":
        data["destination"]["endpoint"] = "https://attacker.invalid"
    evaluate.write_json(path, data)
    arguments = upload_arguments(artifacts, path)
    if change == "confirmation":
        arguments[-1] = "0" * 64
    elif change == "report":
        report_path = artifacts.directory / "report.json"
        altered = json.loads(report_path.read_text())
        altered["results"][0]["response"] = "MUST NOT BE SENT"
        report_path.write_text(json.dumps(altered))
    elif change == "timings":
        timing_path = artifacts.directory / "timings.json"
        altered = json.loads(timing_path.read_text())
        altered["cases"]["deadline"]["calls"][0]["ended_at"] = "2026-11-18T00:00:00.250000+00:00"
        timing_path.write_text(json.dumps(altered))
    monkeypatch.setattr(evaluate, "os", SimpleNamespace(environ=SimpleNamespace(get=forbidden)))
    monkeypatch.setattr(httpx, "Client", forbidden)
    with pytest.raises(SystemExit) as invalid:
        evaluate.main(arguments)
    assert invalid.value.code == 2
    assert not list(artifacts.directory.glob("langsmith-upload-*.json"))


def test_upload_acknowledges_only_frozen_operations_and_blocks_replay(artifacts, monkeypatch):
    preview = preview_for(artifacts)
    path = artifacts.directory / "preview.json"
    evaluate.write_json(path, preview.model_dump())
    sent = []

    def handler(request):
        assert str(request.url) in {ENDPOINTS["us"] + "/runs", ENDPOINTS["us"] + "/feedback"}
        assert request.headers["X-API-Key"] == "SYNTHETIC-KEY-SENTINEL"
        assert request.headers["X-Tenant-Id"] == WORKSPACE_ID
        body = json.loads(request.content)
        assert "SYNTHETIC-KEY-SENTINEL" not in request.content.decode()
        sent.append(body)
        return httpx.Response(200, json={})

    install_transport(monkeypatch, handler)
    monkeypatch.setenv("LANGSMITH_API_KEY", "SYNTHETIC-KEY-SENTINEL")
    arguments = upload_arguments(artifacts, path)
    assert evaluate.main(arguments) == 0
    assert sent == [operation.body for operation in preview.operations]
    receipt = next(artifacts.directory.glob("langsmith-upload-*.json"))
    data = json.loads(receipt.read_text())
    assert data["status"] == "complete"
    assert data["acknowledged"] == len(sent)
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert "SYNTHETIC-KEY-SENTINEL" not in receipt.read_text()
    with pytest.raises(SystemExit) as replay:
        evaluate.main(arguments)
    assert replay.value.code == 2
    assert len(sent) == len(preview.operations)


@pytest.mark.parametrize("failure", ["timeout", 302, 401, 429, 500])
def test_partial_upload_stops_without_retry_or_sensitive_errors(artifacts, monkeypatch, failure):
    preview = preview_for(artifacts)
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200)
        if failure == "timeout":
            raise httpx.ReadTimeout("DO NOT LOG SYNTHETIC-KEY-SENTINEL", request=request)
        return httpx.Response(failure, headers={"Location": "https://attacker.invalid"},
                              text="DO NOT LOG SYNTHETIC-KEY-SENTINEL")

    install_transport(monkeypatch, handler)
    receipt_path = artifacts.directory / "receipt.json"
    receipt = upload_operations(preview, receipt_path, "SYNTHETIC-KEY-SENTINEL")
    assert receipt["status"] == "incomplete"
    assert receipt["attempted"] == 2
    assert receipt["acknowledged"] == 1
    assert len(requests) == 2
    assert receipt["error_code"] == ("network_error" if failure == "timeout" else f"http_{failure}")
    assert "SYNTHETIC-KEY-SENTINEL" not in receipt_path.read_text()


def test_missing_or_invalid_api_key_does_not_start_upload(artifacts, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid credentials caused a request")

    monkeypatch.setattr(httpx, "Client", forbidden)
    preview = preview_for(artifacts)
    receipt = artifacts.directory / "receipt.json"
    for key in ("", "illegal\nheader"):
        with pytest.raises(ValueError, match="LANGSMITH_API_KEY"):
            upload_operations(preview, receipt, key)
    assert not receipt.exists()


def test_configured_credential_cannot_be_embedded_in_a_trace(artifacts, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Credential in payload caused a request")

    monkeypatch.setattr(httpx, "Client", forbidden)
    preview = preview_for(artifacts)
    preview.operations[0].body["outputs"]["response"] = 'SECRET-"QUOTED"-KEY'
    receipt = artifacts.directory / "receipt.json"
    with pytest.raises(ValueError, match="credential appears"):
        upload_operations(preview, receipt, 'SECRET-"QUOTED"-KEY')
    assert not receipt.exists()
