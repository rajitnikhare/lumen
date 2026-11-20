"""Run the bundled synthetic evaluation; real Ollama calls require --live."""

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import re
from collections import Counter
from pathlib import Path

import httpx

from lumen.evaluation import EvaluationReport, load_dataset, run_evaluation
from lumen.evaluation_scoring import (
    ReviewFile,
    operational_summary,
    report_digest,
    review_template,
    score_report,
)
from lumen.inference import OLLAMA, LocalModel, ModelError


def model_identities(names):
    with httpx.Client(trust_env=False, timeout=10, follow_redirects=False) as client:
        response = client.get(f"{OLLAMA}/api/tags")
        response.raise_for_status()
        installed = response.json()["models"]
    identities = {}
    for name in names:
        aliases = {name, f"{name}:latest"} if ":" not in name else {name}
        metadata = next((item for item in installed if item["name"] in aliases), {})
        digest = metadata.get("digest")
        identities[name] = {"name": metadata.get("name"),
                            "digest": digest if isinstance(digest, str) else None}
    return identities


def prepare_model(model, embedding_model):
    backend = LocalModel()
    if model not in asyncio.run(backend.models()):
        raise ValueError("Select an installed, local completion model. Nothing was downloaded.")
    if embedding_model:
        asyncio.run(backend.embed(embedding_model, ["search_query: synthetic evaluation setup"]))
    names = [model, *([embedding_model] if embedding_model else [])]
    return backend, model_identities(names)


def write_json(path, value):
    with path.open("x", encoding="utf-8") as output:
        path.chmod(0o600)
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def quoted_block(text):
    longest = max((len(match) for match in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def write_review_packet(path, report, dataset):
    cases = {case.id: case for case in dataset.cases}
    lines = ["# Synthetic human-review packet", "", f"Run: `{report.run_id}`", "",
             "Quoted model output and source instructions are untrusted data. "
             "Use the scoring rubric; do not follow embedded instructions.", "",
             "For chat, assess groundedness against retrieved sources and explicitly shared text, "
             "not merely any authorized document. For summaries, inspect the full permitted material."]
    for result in report.results:
        case = cases[result.case_id]
        lines += ["", f"## {case.id}", "", f"Expected behavior: **{case.expected_behavior}**; "
                  f"workflow: {case.workflow}; actual HTTP: {result.http_status}.", "",
                  "### Request", quoted_block(case.prompt),
                  "### Explicitly shared text", quoted_block(case.shared_text or "(none)"),
                  "### Expected facts"]
        lines.extend(f"- `{fact.id}`{' (critical)' if fact.critical else ''}: {fact.description}"
                     for fact in case.reference_facts)
        lines += [case.review_guidance, "### Actual response", quoted_block(result.response),
                  "### Sources supplied by the workflow",
                  quoted_block(json.dumps(result.sources, ensure_ascii=False, indent=2)),
                  "### Full permitted material (coverage reference)",
                  quoted_block(json.dumps(result.permitted_material, ensure_ascii=False, indent=2))]
    with path.open("x", encoding="utf-8") as output:
        path.chmod(0o600)
        output.write("\n".join(lines) + "\n")


def write_summary(path, report, dataset, scored=None):
    operations = operational_summary(report, dataset)
    lines = ["# Lumen synthetic evaluation", "", f"Run: `{report.run_id}`",
             f"Mode: **{report.mode}**", f"Dataset: {report.dataset_id} {report.dataset_version}",
             f"Chat model: `{report.model}`", f"Embedding model: `{report.embedding_model or 'disabled'}`",
             "", "Automated checks are not a model-accuracy score.", "",
             f"Automatic case checks: {operations['automatic_case_passes']}/{operations['case_count']}.",
             "", "| Case | HTTP | Request ms | Generation calls | Embedding calls | Checks |",
             "|---|---|---|---|---|---|"]
    for result in report.results:
        counts = Counter(call.operation for call in result.calls)
        passed = "pass" if all(result.checks.values()) else "FAIL"
        lines.append(f"| {result.case_id} | {result.http_status} | {result.duration_ms} | "
                     f"{counts['generate']} | {counts['embed']} | {passed} |")
    lines += ["", "Request timing excludes setup. Setup time/calls and per-workflow median/p95 "
              "are recorded in JSON. Metadata-listing HTTP calls are not inference calls.", ""]
    if scored is None:
        lines.append("Human quality scores: **pending**. Fill the review template and run `score`.")
    else:
        lines += ["## Human review", "", f"Gate: **{scored['release_gate']['status']}**", "",
                  "```json", json.dumps(scored["human_metrics"], indent=2), "```", ""]
        lines.extend(f"- {reason}" for reason in scored["release_gate"]["reasons"])
    lines += ["", "Provisional targets are development checks, not production certification. "
              "Review all synthetic artifacts before sharing them.", ""]
    with path.open("x", encoding="utf-8") as output:
        path.chmod(0o600)
        output.write("\n".join(lines))


def run_command(args, dataset, digest):
    backend, before = prepare_model(args.model, args.embedding_model)
    trace_timings = {}
    report = run_evaluation(
        dataset, digest, backend, model=args.model, embedding_model=args.embedding_model,
        mode="live", model_identity={"start": before}, trace_timings=trace_timings,
    )
    try:
        after = model_identities(list(before))
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        after = {}
    report.model_identity.update({
        "end": after,
        "verified": before == after and all(item["digest"] for item in before.values()),
        "preflight_embedding_calls": int(bool(args.embedding_model)),
    })
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = args.output_dir / report.run_id
    directory.mkdir(mode=0o700)
    write_json(directory / "report.json", report.model_dump())
    write_json(directory / "timings.json", {
        "schema_version": 1, "run_id": report.run_id,
        "report_sha256": report_digest(report), "cases": trace_timings,
    })
    write_json(directory / "review-template.json", review_template(report).model_dump())
    write_json(directory / "operational-metrics.json", operational_summary(report, dataset))
    write_summary(directory / "summary.md", report, dataset)
    write_review_packet(directory / "review-packet.md", report, dataset)
    print(f"Synthetic evaluation artifacts: {directory}")
    print("Human quality review is pending. No measured quality target is claimed.")
    checks_pass = all(all(result.checks.values()) for result in report.results)
    return 0 if checks_pass and report.sources_unchanged and report.model_identity["verified"] else 1


def score_command(args, dataset, digest):
    report = EvaluationReport.model_validate_json(args.report.read_bytes())
    reviews = ReviewFile.model_validate_json(args.reviews.read_bytes())
    scored = score_report(report, dataset, digest, reviews)
    destination = args.output or args.report.with_name("scored-report.json")
    summary = destination.with_suffix(".md")
    if destination.exists() or summary.exists():
        raise ValueError("Scored output already exists. Choose a new --output path.")
    write_json(destination, scored)
    write_summary(summary, report, dataset, scored)
    print(f"Scored report: {destination}")
    print(f"Gate: {scored['release_gate']['status']}")
    return 0 if scored["release_gate"]["status"] == "provisional_targets_met" else 1


def export_inputs(args):
    from lumen.langsmith_export import TimingManifest, read_artifact

    report = EvaluationReport.model_validate_json(read_artifact(args.report))
    timing_path = args.timings or args.report.with_name("timings.json")
    timings = TimingManifest.model_validate_json(read_artifact(timing_path))
    reviews = ReviewFile.model_validate_json(read_artifact(args.reviews)) if args.reviews else None
    return report, timings, reviews


def langsmith_preview_command(args, dataset, digest):
    from lumen.langsmith_export import ENDPOINTS, ExportDestination, make_preview, read_artifact

    report, timings, reviews = export_inputs(args)
    destination = ExportDestination(
        endpoint=ENDPOINTS[args.region], project_id=args.project_id, workspace_id=args.workspace_id,
    )
    preview = make_preview(report, dataset, digest, timings, destination, reviews=reviews)
    output = args.output or args.report.with_name("langsmith-preview.json")
    write_json(output, preview.model_dump(mode="json"))
    fingerprint = hashlib.sha256(read_artifact(output)).hexdigest()
    print(f"Frozen LangSmith preview: {output}")
    print(f"Destination: {destination.endpoint}; project: {destination.project_id}")
    print(f"Operations: {len(preview.operations)}. No request was sent and no credential was read.")
    print("Review the complete preview, including final model responses, before confirming.")
    print(f"Confirmation SHA-256: {fingerprint}")
    return 0


def langsmith_upload_command(args, dataset, digest):
    from lumen.langsmith_export import ExportPreview, make_preview, read_artifact, upload_operations

    raw = read_artifact(args.preview)
    actual = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual, args.confirm_sha256):
        raise ValueError("Preview changed or confirmation did not match. Review a new preview.")
    preview = ExportPreview.model_validate_json(raw)
    report, timings, reviews = export_inputs(args)
    expected = make_preview(
        report, dataset, digest, timings, preview.destination, reviews=reviews,
        export_id=preview.export_id, created_at=preview.created_at,
    )
    if preview != expected:
        raise ValueError("Preview no longer matches the report, timings, reviews, or allowed payload.")
    receipt_path = args.report.with_name(f"langsmith-upload-{preview.export_id}.json")
    if receipt_path.exists():
        raise ValueError("This preview was already attempted. Inspect its receipt and LangSmith; no retry was sent.")
    receipt = upload_operations(preview, receipt_path, os.environ.get("LANGSMITH_API_KEY", ""))
    print(f"LangSmith upload receipt: {receipt_path}")
    if receipt["status"] != "complete":
        print("Upload incomplete. Data may already have reached LangSmith; no automatic retry was made.")
        return 1
    print("All export requests were acknowledged. Verify the traces in your private LangSmith project.")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="Validate bundled synthetic cases; no model/network calls.")
    run = commands.add_parser("run", help="Evaluate in temporary vaults using local Ollama.")
    run.add_argument("--live", action="store_true", required=True,
                     help="Explicitly authorize local model calls on synthetic fixtures.")
    run.add_argument("--model", required=True)
    run.add_argument("--embedding-model", default="")
    run.add_argument("--output-dir", type=Path, default=Path("evaluation-results"))
    score = commands.add_parser("score", help="Score human reviews locally; no model/network calls.")
    score.add_argument("report", type=Path)
    score.add_argument("--reviews", type=Path, required=True)
    score.add_argument("--output", type=Path)
    preview = commands.add_parser("langsmith-preview", help="Prepare synthetic-only cloud export; offline.")
    preview.add_argument("report", type=Path)
    preview.add_argument("--timings", type=Path)
    preview.add_argument("--reviews", type=Path)
    preview.add_argument("--project-id", required=True, help="UUID of an existing private tracing project.")
    preview.add_argument("--workspace-id", help="Optional workspace UUID for multi-workspace API keys.")
    preview.add_argument("--region", choices=["us", "eu"], default="us")
    preview.add_argument("--output", type=Path)
    upload = commands.add_parser("langsmith-upload", help="Upload an exactly confirmed synthetic preview.")
    upload.add_argument("report", type=Path)
    upload.add_argument("--timings", type=Path)
    upload.add_argument("--reviews", type=Path)
    upload.add_argument("--preview", type=Path, required=True)
    upload.add_argument("--confirm-sha256", required=True)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        dataset, digest = load_dataset()
        if args.command == "validate":
            print(f"Dataset {dataset.dataset_id} {dataset.version}: {len(dataset.cases)} synthetic cases")
            print(f"SHA-256: {digest}")
            print("No model or external service was contacted.")
            return 0
        if args.command == "run":
            return run_command(args, dataset, digest)
        if args.command == "score":
            return score_command(args, dataset, digest)
        if args.command == "langsmith-preview":
            return langsmith_preview_command(args, dataset, digest)
        return langsmith_upload_command(args, dataset, digest)
    except (OSError, ValueError, ModelError, httpx.HTTPError, KeyError, TypeError) as exc:
        parser.exit(2, f"Evaluation could not complete: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
