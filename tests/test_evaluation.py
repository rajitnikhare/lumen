import asyncio
import json
from collections import Counter

import httpx
import pytest
from pydantic import ValidationError

from lumen.evaluation import (
    CaseResult,
    EvaluationDataset,
    EvaluationReport,
    MeasuredModel,
    automatic_checks,
    load_dataset,
    run_evaluation,
)
from lumen.evaluation_scoring import (
    HumanReview,
    latency_summary,
    operational_summary,
    review_template,
    score_report,
)
from lumen.inference import ModelError
from scripts import evaluate


class SyntheticBackend:
    async def models(self):
        return ["test-local:latest"]

    async def generate(self, model, task, data):
        return "Synthetic harness response. This is not a measured model answer."

    async def embed(self, model, texts):
        return [[1.0, 0.0] for _ in texts]


def subset(dataset, identifiers):
    return dataset.model_copy(update={
        "cases": [case for case in dataset.cases if case.id in identifiers],
    })


def test_dataset_covers_required_cases_and_rejects_bad_references():
    dataset, digest = load_dataset()
    assert len(dataset.cases) == 18
    assert len(digest) == 64
    categories = {case.category for case in dataset.cases}
    assert {"answerable", "unanswerable", "paraphrase", "conflict", "stale", "summary",
            "long-summary", "shared-context", "prompt-injection", "high-impact",
            "permission", "revocation", "deletion", "malformed-input"} <= categories
    invalid = dataset.model_dump()
    invalid["cases"][0]["expected_documents"] = ["not-present"]
    with pytest.raises(ValidationError, match="Expected documents"):
        EvaluationDataset.model_validate(invalid)
    invalid = dataset.model_dump()
    invalid["provenance"] = "personal"
    with pytest.raises(ValidationError):
        EvaluationDataset.model_validate(invalid)


def test_simulated_suite_exercises_real_routes_without_quality_claims():
    dataset, digest = load_dataset()
    report = run_evaluation(
        dataset, digest, SyntheticBackend(), model="test-local:latest", mode="simulated",
    )
    assert len(report.results) == 18
    assert report.sources_unchanged
    assert all(all(result.checks.values()) for result in report.results)
    results = {result.case_id: result for result in report.results}
    assert len(results["summary-long"].calls) > 1
    for identifier in ("unauthorized-document", "revoked-history", "deleted-history"):
        assert results[identifier].sources == []
        assert results[identifier].permitted_material == []
    assert results["revoked-history"].setup_calls
    assert results["deleted-history"].setup_calls
    assert results["unsupported-import"].http_status == 400
    assert results["empty-question"].http_status == 422
    assert results["empty-question"].calls == []
    assert operational_summary(report, dataset)["automatic_case_passes"] == 18
    scored = score_report(report, dataset, digest, review_template(report))
    assert scored["human_metrics"] is None
    assert scored["measurement_kind"] == "harness_test_only"
    assert scored["release_gate"]["status"] == "blocked"


def test_semantic_calls_and_setup_calls_are_separate():
    from lumen.langsmith_export import TimingManifest, validate_timings

    dataset, digest = load_dataset()
    dataset = subset(dataset, {"deadline", "unauthorized-document", "revoked-history"})
    timings = {}
    report = run_evaluation(
        dataset, digest, SyntheticBackend(), model="test-local:latest",
        embedding_model="test-embed", mode="simulated", trace_timings=timings,
    )
    manifest = TimingManifest(run_id=report.run_id,
                              report_sha256=review_template(report).report_sha256, cases=timings)
    validate_timings(report, manifest)
    results = {result.case_id: result for result in report.results}
    operations = Counter(call.operation for call in results["deadline"].calls)
    assert operations == {"embed": 2, "generate": 1}
    assert operational_summary(report, dataset)["workflows"]["chat"]["expected_document_recall"]["value"] == 1.0
    assert Counter(call.operation for call in results["deadline"].setup_calls) == {"embed": 1}
    assert Counter(call.operation for call in results["revoked-history"].calls) == {"generate": 1}
    assert all(all(result.checks.values()) for result in report.results)


def test_meter_records_canaries_and_failed_calls_without_payloads():
    class BrokenBackend(SyntheticBackend):
        async def generate(self, model, task, data):
            raise ModelError("Synthetic failure")

    measured = MeasuredModel(BrokenBackend())
    measured.forbidden_markers = ["SYNTHETIC-CANARY-91"]
    with pytest.raises(ModelError):
        asyncio.run(measured.generate("test-local:latest", "Task", {"text": "SYNTHETIC-CANARY-91"}))
    call = measured.calls[0]
    assert not call.succeeded
    assert call.duration_ms >= 0
    assert call.input_violations == ["forbidden_input_marker_1"]
    assert "SYNTHETIC-CANARY-91" not in call.model_dump_json()


@pytest.mark.parametrize("stage", ["setup", "request"])
def test_model_failures_are_reported_without_losing_case_results(stage):
    class BrokenBackend(SyntheticBackend):
        async def models(self):
            if stage == "setup":
                raise ModelError("Synthetic setup failure")
            return await super().models()

        async def generate(self, model, task, data):
            raise ModelError("Synthetic request failure")

    dataset, digest = load_dataset()
    report = run_evaluation(
        subset(dataset, {"deadline"}), digest, BrokenBackend(),
        model="test-local:latest", mode="simulated",
    )
    result = report.results[0]
    assert result.http_status == 502
    assert result.outcome == ("setup_failed" if stage == "setup" else "request_failed")
    assert not all(result.checks.values())
    if stage == "request":
        assert len(result.calls) == 1
        assert not result.calls[0].succeeded


def test_output_canary_checks_the_answer_not_quoted_source_material():
    class InjectedBackend(SyntheticBackend):
        async def generate(self, model, task, data):
            return "LUMEN_EVAL_INJECTION_73"

    dataset, digest = load_dataset()
    dataset = subset(dataset, {"document-injection"})
    report = run_evaluation(
        dataset, digest, InjectedBackend(), model="test-local:latest", mode="simulated",
    )
    result = report.results[0]
    assert result.http_status == 200
    assert result.checks["input_canaries_absent"]
    assert not result.checks["output_canaries_absent"]
    assert "LUMEN_EVAL_INJECTION_73" in result.sources[0]["text"]


def test_source_changes_during_run_are_detected(monkeypatch):
    from lumen import evaluation

    snapshots = iter([{"source": "before"}, {"source": "after"}])
    monkeypatch.setattr(evaluation, "source_fingerprints", lambda: next(snapshots))
    dataset, digest = load_dataset()
    report = run_evaluation(
        subset(dataset, {"empty-question"}), digest, SyntheticBackend(),
        model="test-local:latest", mode="simulated",
    )
    assert not report.sources_unchanged
    assert report.source_fingerprints == {"source": "before"}


def scoring_fixture():
    dataset, digest = load_dataset()
    dataset = subset(dataset, {"deadline", "summary-short", "missing-confirmation", "high-impact-medical"})
    results = [CaseResult(
        case_id=case.id, outcome="completed", http_status=200, response="Handcrafted unit-test output",
        duration_ms=10.0, setup_duration_ms=1.0, calls=[], setup_calls=[],
        checks=automatic_checks(case, 200, "Handcrafted unit-test output", [], []),
        retrieved_documents=[], sources=[], permitted_material=[],
    ) for case in dataset.cases]
    report = EvaluationReport(
        run_id="handcrafted-unit-test", created_at="2026-11-18T00:00:00Z", mode="live",
        dataset_id=dataset.dataset_id, dataset_version=dataset.version, dataset_sha256=digest,
        evaluator_version="test", model="handcrafted-test-only", embedding_model="",
        model_identity={"verified": True}, source_fingerprints={}, sources_unchanged=True,
        environment={}, results=results,
    )
    reviews = review_template(report)
    reviews.reviewer = "synthetic-test-reviewer"
    for case, review in zip(dataset.cases, reviews.reviews, strict=True):
        review.personal_claims = len(case.reference_facts)
        review.supported_personal_claims = len(case.reference_facts)
        review.covered_fact_ids = [fact.id for fact in case.reference_facts]
        review.answer_correct = True if case.expected_behavior == "answer" else None
        review.abstained = case.expected_behavior != "answer"
        review.escalated = case.expected_behavior == "human_review"
        review.critical_errors = 0
    return dataset, digest, report, reviews


def test_human_metrics_have_explicit_denominators():
    dataset, digest, report, reviews = scoring_fixture()
    scored = score_report(report, dataset, digest, reviews)
    metrics = scored["human_metrics"]
    assert scored["model"] == "handcrafted-test-only"
    assert scored["dataset"]["sha256"] == digest
    assert metrics["answer_correctness"] == {"value": 1.0, "numerator": 2, "denominator": 2, "reviewed": 2}
    assert metrics["groundedness"]["denominator"] == 4
    assert metrics["summary_coverage"]["numerator"] == 3
    assert metrics["appropriate_abstention"]["denominator"] == 1
    assert scored["release_gate"]["status"] == "provisional_targets_met"
    deadline = next(review for review in reviews.reviews if review.case_id == "deadline")
    deadline.answer_correct = False
    deadline.personal_claims = 2
    deadline.critical_errors = 1
    scored = score_report(report, dataset, digest, reviews)
    assert scored["human_metrics"]["answer_correctness"]["value"] == 0.5
    assert scored["human_metrics"]["groundedness"]["value"] == 0.8
    assert scored["human_metrics"]["critical_errors"]["observed"] == 1
    assert scored["release_gate"]["status"] == "blocked"


def test_unreviewed_outputs_are_unknown_not_automatic_passes():
    dataset, digest, report, _ = scoring_fixture()
    scored = score_report(report, dataset, digest, review_template(report))
    assert len(scored["pending_cases"]) == 4
    assert scored["human_metrics"]["answer_correctness"]["value"] is None
    assert scored["human_metrics"]["groundedness"]["value"] is None
    assert scored["release_gate"]["status"] == "blocked"


@pytest.mark.parametrize("change", ["run", "response", "dataset", "duplicate", "fact"])
def test_reviews_cannot_be_applied_to_different_or_incomplete_runs(change):
    dataset, digest, report, reviews = scoring_fixture()
    if change == "run":
        reviews.run_id = "another-run"
    elif change == "response":
        report.results[0].response = "Changed after human review"
    elif change == "dataset":
        digest = "different-dataset"
    elif change == "duplicate":
        reviews.reviews.append(reviews.reviews[0])
    else:
        reviews.reviews[0].covered_fact_ids = ["invented-fact"]
    with pytest.raises(ValueError):
        score_report(report, dataset, digest, reviews)


@pytest.mark.parametrize("fields", [
    {"personal_claims": -1}, {"personal_claims": True},
    {"personal_claims": 1, "supported_personal_claims": 2},
    {"answer_correct": True, "critical_errors": 1},
    {"covered_fact_ids": ["duplicate", "duplicate"]},
    {"override_approval": True},
])
def test_invalid_human_scores_are_rejected(fields):
    with pytest.raises(ValidationError):
        HumanReview(case_id="test", **fields)


def test_automatic_failures_cannot_be_overridden_by_positive_reviews():
    dataset, digest, report, _ = scoring_fixture()
    report.results[0].retrieved_documents = ["unknown"]
    report.results[0].checks["sources_authorized"] = False
    reviews = review_template(report)
    _, _, _, complete = scoring_fixture()
    reviews.reviewer = complete.reviewer
    reviews.reviews = complete.reviews
    scored = score_report(report, dataset, digest, reviews)
    assert scored["release_gate"]["status"] == "blocked"
    assert scored["operational_metrics"]["automatic_failures"]


def test_scoring_rejects_removed_automatic_checks():
    dataset, digest, report, _ = scoring_fixture()
    report.results[0].checks = {}
    with pytest.raises(ValueError, match="inconsistent"):
        score_report(report, dataset, digest, review_template(report))


def test_failures_count_against_accuracy_and_summary_coverage():
    dataset, digest, report, _ = scoring_fixture()
    summary = next(result for result in report.results if result.case_id == "summary-short")
    summary.http_status = 502
    summary.outcome = "request_failed"
    summary.checks["expected_http_status"] = False
    reviews = review_template(report)
    scored = score_report(report, dataset, digest, reviews)
    assert scored["human_metrics"]["answer_correctness"]["reviewed"] == 1
    assert scored["human_metrics"]["summary_coverage"]["numerator"] == 0
    assert scored["human_metrics"]["summary_coverage"]["denominator"] == 3
    next(review for review in reviews.reviews if review.case_id == "summary-short").answer_correct = True
    with pytest.raises(ValueError, match="HTTP failure"):
        score_report(report, dataset, digest, reviews)


def test_nearest_rank_p95_and_empty_samples():
    assert latency_summary([]) == {"samples": 0, "median_ms": None, "p95_ms": None}
    assert latency_summary(list(range(1, 21))) == {"samples": 20, "median_ms": 10.5, "p95_ms": 19}


def test_validate_and_score_commands_do_not_contact_models(monkeypatch, tmp_path, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Offline command attempted a model request")

    monkeypatch.setattr(evaluate, "prepare_model", forbidden)
    assert evaluate.main(["validate"]) == 0
    assert "18 synthetic cases" in capsys.readouterr().out
    with pytest.raises(SystemExit) as missing_opt_in:
        evaluate.main(["run", "--model", "test-local:latest"])
    assert missing_opt_in.value.code == 2
    dataset, digest, report, reviews = scoring_fixture()
    monkeypatch.setattr(evaluate, "load_dataset", lambda: (dataset, digest))
    report_path = tmp_path / "report.json"
    review_path = tmp_path / "reviews.json"
    report_path.write_text(report.model_dump_json())
    review_path.write_text(reviews.model_dump_json())
    assert evaluate.main(["score", str(report_path), "--reviews", str(review_path)]) == 0
    assert (tmp_path / "scored-report.md").exists()
    with pytest.raises(SystemExit) as overwrite:
        evaluate.main(["score", str(report_path), "--reviews", str(review_path)])
    assert overwrite.value.code == 2


def test_run_writes_private_artifacts_with_pending_human_review(monkeypatch, tmp_path):
    from lumen import langsmith_export

    def forbidden_upload(*args, **kwargs):
        pytest.fail("A normal evaluation run tried to export traces")

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "UNUSED-SYNTHETIC-KEY")
    monkeypatch.setattr(langsmith_export, "upload_operations", forbidden_upload)
    dataset, digest = load_dataset()
    dataset = subset(dataset, {"deadline", "empty-question"})
    identity = {"test-local:latest": {"name": "test-local:latest", "digest": "a" * 64}}
    monkeypatch.setattr(evaluate, "load_dataset", lambda: (dataset, digest))
    monkeypatch.setattr(evaluate, "prepare_model", lambda *args: (SyntheticBackend(), identity))
    monkeypatch.setattr(evaluate, "model_identities", lambda *args: identity)
    assert evaluate.main(["run", "--live", "--model", "test-local:latest",
                          "--output-dir", str(tmp_path)]) == 0
    directory = next(tmp_path.iterdir())
    assert directory.stat().st_mode & 0o777 == 0o700
    report = json.loads((directory / "report.json").read_text())
    reviews = json.loads((directory / "review-template.json").read_text())
    assert report["model_identity"]["verified"] is True
    timings = json.loads((directory / "timings.json").read_text())
    assert timings["report_sha256"] == review_template(EvaluationReport.model_validate(report)).report_sha256
    assert set(timings["cases"]) == {"deadline", "empty-question"}
    assert all(review["answer_correct"] is None for review in reviews["reviews"])
    assert (directory / "report.json").stat().st_mode & 0o777 == 0o600
    assert "pending" in (directory / "summary.md").read_text()
    assert "What is Project Cedar" in (directory / "review-packet.md").read_text()
    with pytest.raises(FileExistsError):
        evaluate.write_json(directory / "report.json", {})


def test_quoted_model_output_cannot_escape_its_markdown_fence():
    text = "```\nUntrusted content\n````"
    block = evaluate.quoted_block(text)
    assert block.startswith("`````\n")
    assert block.endswith("\n`````")


def test_model_identity_uses_fixed_loopback_and_resolves_embedding_alias(monkeypatch):
    original = httpx.Client

    def handler(request):
        assert str(request.url) == "http://127.0.0.1:11434/api/tags"
        return httpx.Response(200, json={"models": [
            {"name": "chat:latest", "digest": "a" * 64},
            {"name": "nomic-embed-text:latest", "digest": "b" * 64},
        ]})

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(evaluate.httpx, "Client", client)
    identities = evaluate.model_identities(["chat:latest", "nomic-embed-text"])
    assert identities["nomic-embed-text"] == {
        "name": "nomic-embed-text:latest", "digest": "b" * 64,
    }
