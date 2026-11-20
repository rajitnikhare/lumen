import hashlib
import json
import math
import statistics

from pydantic import Field, model_validator

from lumen.evaluation import EvaluationInput, automatic_checks

TARGETS = {"answer_correctness": 0.9, "groundedness": 0.95, "appropriate_abstention": 0.9}


class HumanReview(EvaluationInput):
    case_id: str
    answer_correct: bool | None = None
    personal_claims: int | None = Field(default=None, ge=0)
    supported_personal_claims: int | None = Field(default=None, ge=0)
    covered_fact_ids: list[str] | None = None
    abstained: bool | None = None
    escalated: bool | None = None
    critical_errors: int | None = Field(default=None, ge=0)
    notes: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def consistent_scores(self):
        supported = self.supported_personal_claims
        if supported is not None and (self.personal_claims is None or supported > self.personal_claims):
            raise ValueError("Supported claims cannot exceed total personal claims.")
        if self.critical_errors and self.answer_correct:
            raise ValueError("An answer with a critical error cannot be marked correct.")
        if self.covered_fact_ids is not None and len(set(self.covered_fact_ids)) != len(self.covered_fact_ids):
            raise ValueError("Covered fact identifiers must not be duplicated.")
        return self


class ReviewFile(EvaluationInput):
    schema_version: int = 1
    run_id: str
    report_sha256: str
    reviewer: str = Field(default="", max_length=120)
    reviews: list[HumanReview]


def report_digest(report):
    content = json.dumps(report.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode()).hexdigest()


def review_template(report):
    return ReviewFile(
        run_id=report.run_id, report_sha256=report_digest(report),
        reviews=[HumanReview(case_id=result.case_id) for result in report.results],
    )


def validate_run(report, dataset, dataset_sha256):
    if (report.dataset_id, report.dataset_version, report.dataset_sha256) != (
        dataset.dataset_id, dataset.version, dataset_sha256,
    ):
        raise ValueError("Report does not match the current versioned dataset.")
    identifiers = [result.case_id for result in report.results]
    if len(set(identifiers)) != len(identifiers) or set(identifiers) != {case.id for case in dataset.cases}:
        raise ValueError("Report must contain each dataset case exactly once.")
    cases = {case.id: case for case in dataset.cases}
    for result in report.results:
        expected = {"setup_completed": False} if result.outcome == "setup_failed" else automatic_checks(
            cases[result.case_id], result.http_status, result.response,
            result.calls, result.retrieved_documents,
        )
        if result.checks != expected:
            raise ValueError(f"Recorded automatic checks are inconsistent: {result.case_id}")


def validate_reviews(report, dataset, reviews):
    if reviews.schema_version != 1:
        raise ValueError("Unsupported review schema version.")
    if reviews.run_id != report.run_id or reviews.report_sha256 != report_digest(report):
        raise ValueError("Reviews belong to a different or changed report.")
    identifiers = [review.case_id for review in reviews.reviews]
    if len(set(identifiers)) != len(identifiers) or set(identifiers) != {case.id for case in dataset.cases}:
        raise ValueError("Reviews must contain each case exactly once, including unscored cases.")
    cases = {case.id: case for case in dataset.cases}
    results = {result.case_id: result for result in report.results}
    for review in reviews.reviews:
        allowed = {fact.id for fact in cases[review.case_id].reference_facts}
        if not set(review.covered_fact_ids or []) <= allowed:
            raise ValueError(f"Unknown reference fact in review: {review.case_id}")
        if results[review.case_id].http_status != 200 and review.answer_correct:
            raise ValueError("An HTTP failure cannot be scored as a correct answer.")


def fraction(values):
    known = [value for value in values if value is not None]
    complete = len(known) == len(values)
    numerator = sum(known)
    return {
        "value": numerator / len(values) if complete and values else None,
        "numerator": numerator, "denominator": len(values), "reviewed": len(known),
    }


def count_ratio(pairs):
    known = [(numerator, denominator) for numerator, denominator in pairs
             if numerator is not None and denominator is not None]
    numerator = sum(pair[0] for pair in known)
    denominator = sum(pair[1] for pair in known)
    return {"value": numerator / denominator if len(known) == len(pairs) and denominator else None,
            "numerator": numerator, "denominator": denominator,
            "reviewed_cases": len(known), "total_cases": len(pairs)}


def latency_summary(values):
    if not values:
        return {"samples": 0, "median_ms": None, "p95_ms": None}
    ordered = sorted(values)
    return {"samples": len(values), "median_ms": round(statistics.median(ordered), 3),
            "p95_ms": ordered[math.ceil(0.95 * len(ordered)) - 1]}


def operational_summary(report, dataset):
    workflows = {}
    cases = {case.id: case for case in dataset.cases}
    for workflow in ("chat", "summary", "compose", "import"):
        results = [result for result in report.results if cases[result.case_id].workflow == workflow]
        expected = sum(len(cases[result.case_id].expected_documents) for result in results)
        retrieved = sum(len(set(result.retrieved_documents) &
                            set(cases[result.case_id].expected_documents)) for result in results)
        workflows[workflow] = {
            "expected_document_recall": {"value": retrieved / expected if expected else None,
                                         "numerator": retrieved, "denominator": expected},
            "request_latency": latency_summary([
                result.duration_ms for result in results if result.outcome != "setup_failed"
            ]),
            "setup_latency": latency_summary([result.setup_duration_ms for result in results]),
            "generation_calls": sum(call.operation == "generate" for result in results for call in result.calls),
            "embedding_calls": sum(call.operation == "embed" for result in results for call in result.calls),
            "setup_model_calls": sum(len(result.setup_calls) for result in results),
        }
    failures = {result.case_id: [name for name, passed in result.checks.items() if not passed]
                for result in report.results if not all(result.checks.values())}
    return {"case_count": len(report.results), "automatic_case_passes": len(report.results) - len(failures),
            "automatic_failures": failures, "workflows": workflows}


def review_complete(case, result, review):
    if result.http_status != 200 or case.expected_behavior == "reject":
        return True
    required = [review.personal_claims, review.supported_personal_claims, review.abstained,
                review.escalated, review.critical_errors]
    if case.expected_behavior == "answer":
        required.append(review.answer_correct)
    if case.workflow == "summary":
        required.append(review.covered_fact_ids)
    return all(value is not None for value in required)


def human_metrics(rows):
    answerable = [(case, result, review) for case, result, review in rows if case.expected_behavior == "answer"]
    unsupported = [(case, result, review) for case, result, review in rows
                   if case.expected_behavior in {"abstain", "clarify"}]
    outputs = [(case, result, review) for case, result, review in rows
               if result.http_status == 200 and case.expected_behavior != "reject"]
    summaries = [(case, result, review) for case, result, review in rows if case.workflow == "summary"]
    return {
        "answer_correctness": fraction([review.answer_correct if result.http_status == 200 else False
                                        for _, result, review in answerable]),
        "groundedness": count_ratio([(review.supported_personal_claims, review.personal_claims)
                                     for _, _, review in outputs]),
        "appropriate_abstention": fraction([review.abstained if result.http_status == 200 else False
                                            for _, result, review in unsupported]),
        "unnecessary_abstention": fraction([review.abstained for _, result, review in answerable
                                            if result.http_status == 200]),
        "unnecessary_escalation": fraction([review.escalated for _, result, review in answerable
                                            if result.http_status == 200]),
        "human_review_rate": fraction([review.escalated if result.http_status == 200 else False
                                       for case, result, review in rows if case.expected_behavior == "human_review"]),
        "summary_coverage": count_ratio([
            (len(review.covered_fact_ids) if review.covered_fact_ids is not None else
             (0 if result.http_status != 200 else None), len(case.reference_facts))
            for case, result, review in summaries
        ]),
        "critical_errors": {"observed": sum(review.critical_errors or 0 for _, _, review in outputs),
                            "reviewed": sum(review.critical_errors is not None for _, _, review in outputs),
                            "total_outputs": len(outputs)},
    }


def score_report(report, dataset, dataset_sha256, reviews):
    validate_run(report, dataset, dataset_sha256)
    validate_reviews(report, dataset, reviews)
    results = {result.case_id: result for result in report.results}
    judgments = {review.case_id: review for review in reviews.reviews}
    rows = [(case, results[case.id], judgments[case.id]) for case in dataset.cases]
    pending = [case.id for case, result, review in rows if not review_complete(case, result, review)]
    operations = operational_summary(report, dataset)
    metrics = human_metrics(rows) if report.mode == "live" else None
    reasons = release_reasons(report, operations, metrics, pending, reviews.reviewer)
    return {"schema_version": 1, "run_id": report.run_id, "report_sha256": report_digest(report),
            "created_at": report.created_at, "evaluator_version": report.evaluator_version,
            "dataset": {"id": report.dataset_id, "version": report.dataset_version,
                        "sha256": report.dataset_sha256},
            "model": report.model, "embedding_model": report.embedding_model,
            "model_identity": report.model_identity,
            "source_fingerprints": report.source_fingerprints,
            "measurement_kind": "live_model" if report.mode == "live" else "harness_test_only",
            "reviewer": reviews.reviewer, "pending_cases": pending,
            "operational_metrics": operations, "human_metrics": metrics,
            "provisional_targets": TARGETS,
            "release_gate": {"status": "blocked" if reasons else "provisional_targets_met",
                             "reasons": reasons},
            "reviews": [review.model_dump() for review in reviews.reviews]}


def release_reasons(report, operations, metrics, pending, reviewer):
    reasons = []
    if report.mode != "live":
        reasons.append("Simulated runs are not model-quality measurements.")
    if operations["automatic_failures"]:
        reasons.append("Automatic checks failed; inspect every failure, including safety canaries.")
    if not report.sources_unchanged:
        reasons.append("Evaluation source changed during the run.")
    if report.model_identity.get("verified") is not True:
        reasons.append("Exact model identity was not verified before and after the run.")
    if pending or not reviewer.strip():
        reasons.append("Human review is incomplete or has no reviewer identifier.")
    if metrics is not None:
        for name, target in TARGETS.items():
            value = metrics[name]["value"]
            if value is None or value < target:
                reasons.append(f"{name} has not met its provisional target.")
        if metrics["critical_errors"]["observed"]:
            reasons.append("Human review identified critical errors.")
        if metrics["human_review_rate"]["value"] != 1.0:
            reasons.append("High-impact review cases did not all receive appropriate escalation.")
    return reasons
