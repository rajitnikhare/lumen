"""Offline-development evaluation against the bundled synthetic dataset, not personal vaults."""

import hashlib
import json
import platform
import secrets
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field, model_validator

from lumen.app import create_app

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "tests" / "fixtures" / "evaluation" / "baseline-v1.json"
EVALUATOR_VERSION = "1.1.0"


class EvaluationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ReferenceFact(EvaluationInput):
    id: str = Field(pattern=r"^[a-z0-9-]+$", max_length=80)
    description: str = Field(min_length=1, max_length=1000)
    critical: bool = False


class SyntheticDocument(EvaluationInput):
    id: str = Field(pattern=r"^[a-z0-9-]+$", max_length=80)
    filename: str = Field(pattern=r"^[a-zA-Z0-9_. -]+$", max_length=200)
    body: str = Field(min_length=1, max_length=100_000)
    authorized: bool = True
    repeat: int = Field(default=1, ge=1, le=500)
    tail: str = Field(default="", max_length=10_000)

    def text(self) -> str:
        return (self.body + "\n") * self.repeat + self.tail


class EvaluationCase(EvaluationInput):
    id: str = Field(pattern=r"^[a-z0-9-]+$", max_length=80)
    category: str = Field(min_length=1, max_length=80)
    workflow: Literal["chat", "summary", "compose", "import"] = "chat"
    prompt: str = Field(default="", max_length=8000)
    shared_text: str = Field(default="", max_length=8000)
    documents: list[SyntheticDocument] = Field(default_factory=list, max_length=8)
    history_action: Literal["none", "revoke", "delete"] = "none"
    expected_status: int = Field(default=200, ge=100, le=599)
    expected_behavior: Literal["answer", "abstain", "clarify", "human_review", "reject"] = "answer"
    expected_documents: list[str] = Field(default_factory=list)
    reference_facts: list[ReferenceFact] = Field(default_factory=list)
    forbidden_input_markers: list[str] = Field(default_factory=list)
    forbidden_output_markers: list[str] = Field(default_factory=list)
    review_guidance: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def consistent_references(self):
        identifiers = [document.id for document in self.documents]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Document identifiers must be unique within a case.")
        if not set(self.expected_documents) <= set(identifiers):
            raise ValueError("Expected documents must refer to this case's documents.")
        if self.workflow in {"summary", "import"} and len(self.documents) != 1:
            raise ValueError("Summary/import cases need exactly one document.")
        if self.history_action != "none" and (
            self.workflow != "chat" or not self.documents
            or not all(document.authorized for document in self.documents)
        ):
            raise ValueError("History cases need chat and initially authorized documents.")
        fact_ids = [fact.id for fact in self.reference_facts]
        if len(set(fact_ids)) != len(fact_ids):
            raise ValueError("Reference fact identifiers must be unique.")
        if any(len(document.text()) > 600_000 for document in self.documents):
            raise ValueError("Synthetic material exceeds the extraction budget.")
        return self


class EvaluationDataset(EvaluationInput):
    schema_version: Literal[1]
    dataset_id: Literal["lumen-synthetic-baseline"]
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    provenance: Literal["synthetic"]
    cases: list[EvaluationCase] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_cases(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("Case identifiers must be unique.")
        return self


class ModelCall(EvaluationInput):
    operation: Literal["generate", "embed"]
    duration_ms: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    succeeded: bool = False
    input_violations: list[str] = Field(default_factory=list)


class CaseResult(EvaluationInput):
    case_id: str
    outcome: Literal["completed", "request_failed", "setup_failed"]
    http_status: int | None
    response: str
    duration_ms: float = Field(ge=0, allow_inf_nan=False)
    setup_duration_ms: float = Field(ge=0, allow_inf_nan=False)
    calls: list[ModelCall]
    setup_calls: list[ModelCall]
    checks: dict[str, bool]
    retrieved_documents: list[str]
    sources: list[dict]
    permitted_material: list[dict]


class EvaluationReport(EvaluationInput):
    schema_version: Literal[1] = 1
    run_id: str
    created_at: str
    mode: Literal["live", "simulated"]
    dataset_id: str
    dataset_version: str
    dataset_sha256: str
    evaluator_version: str
    model: str
    embedding_model: str
    model_identity: dict
    source_fingerprints: dict[str, str]
    sources_unchanged: bool
    environment: dict[str, str]
    results: list[CaseResult]


def load_dataset(path: Path = DATASET_PATH) -> tuple[EvaluationDataset, str]:
    raw = path.read_bytes()
    return EvaluationDataset.model_validate_json(raw), hashlib.sha256(raw).hexdigest()


class MeasuredModel:
    def __init__(self, backend):
        self.backend = backend
        self.calls: list[ModelCall] = []
        self.timings: list[dict] = []
        self.forbidden_markers: list[str] = []

    async def models(self):
        return await self.backend.models()

    async def generate(self, model, task, data):
        return await self.measure("generate", self.backend.generate, model, task, data)

    async def embed(self, model, texts):
        return await self.measure("embed", self.backend.embed, model, texts)

    async def measure(self, operation, function, *arguments):
        payload = json.dumps(arguments[1:], ensure_ascii=False)
        violations = [f"forbidden_input_marker_{index}" for index, marker
                      in enumerate(self.forbidden_markers, 1) if marker in payload]
        call = ModelCall(operation=operation, input_violations=violations)
        self.calls.append(call)
        timing = {"operation": operation, "started_at": datetime.now(UTC).isoformat()}
        self.timings.append(timing)
        started = time.perf_counter()
        try:
            result = await function(*arguments)
            call.succeeded = True
            return result
        finally:
            call.duration_ms = round((time.perf_counter() - started) * 1000, 3)
            timing["ended_at"] = datetime.now(UTC).isoformat()


class SetupFailure(Exception):
    def __init__(self, stage: str, status: int):
        self.stage = stage
        self.status = status
        super().__init__(f"{stage} returned HTTP {status}.")


def require_success(response, stage):
    if response.is_error:
        raise SetupFailure(stage, response.status_code)
    return response.json()


def upload(client, document):
    return client.post(
        "/api/documents", params={"filename": document.filename, "authorized": document.authorized},
        content=document.text().encode("utf-8"),
    )


def prepare_case(client, case, model, embedding_model):
    session = require_success(client.get("/api/session"), "session")
    client.headers["X-Lumen-CSRF"] = session["csrf"]
    require_success(client.post("/api/unlock", json={"passphrase": secrets.token_urlsafe(32)}), "unlock")
    settings = {"model": model, "embedding_model": embedding_model}
    require_success(client.put("/api/settings", json=settings), "settings")
    identifiers = {}
    if case.workflow != "import":
        for document in case.documents:
            saved = require_success(upload(client, document), "import")
            identifiers[document.id] = saved["id"]
    if case.history_action != "none":
        prepare_history(client, case, identifiers)
    return identifiers


def prepare_history(client, case, identifiers):
    require_success(client.post("/api/chat", json={"message": case.prompt}), "history prelude")
    for identifier in identifiers.values():
        if case.history_action == "revoke":
            response = client.put(f"/api/access/document/{identifier}", json={"authorized": False})
        else:
            preview = require_success(
                client.post(f"/api/delete/document/{identifier}/preview"), "deletion preview"
            )
            response = client.post(f"/api/approvals/{preview['id']}/confirm")
        require_success(response, "history access change")


def execute_case(client, case, identifiers):
    if case.workflow == "import":
        return upload(client, case.documents[0])
    if case.workflow == "summary":
        identifier = identifiers[case.documents[0].id]
        return client.post(f"/api/documents/{identifier}/summary", json={"focus": case.prompt})
    if case.workflow == "compose":
        return client.post("/api/compose", json={
            "instructions": case.prompt, "shared_text": case.shared_text,
        })
    return client.post("/api/chat", json={
        "message": case.prompt, "shared_text": case.shared_text,
        "use_history": case.history_action != "none",
    })


def permitted_material(state, identifiers):
    material = []
    for fixture_id, identifier in identifiers.items():
        document = state.vault.get("document", identifier)
        if document and document["authorized"]:
            material.append({"document": fixture_id, "title": document["title"],
                             "chunks": document["chunks"]})
    return material


def automatic_checks(case, status, text, calls, retrieved):
    allowed = {document.id for document in case.documents if document.authorized}
    if case.history_action != "none":
        allowed.clear()
    return {
        "expected_http_status": status == case.expected_status,
        "nonempty_response": bool(text.strip()),
        "input_canaries_absent": not any(call.input_violations for call in calls),
        "output_canaries_absent": not any(
            marker.casefold() in text.casefold() for marker in case.forbidden_output_markers
        ),
        "sources_authorized": set(retrieved) <= allowed,
        "invalid_input_avoids_inference": case.expected_behavior != "reject" or not calls,
    }


def collect_result(case, response, elapsed, measured, setup_calls, setup_ms, material, identifiers):
    try:
        payload = response.json()
    except ValueError:
        payload = {"detail": "Non-JSON response."}
    if not isinstance(payload, dict):
        payload = {}
    text = payload.get("answer", payload.get("summary", payload.get("body", "")))
    if response.is_error:
        text = str(payload.get("detail", "Request failed."))
    if not isinstance(text, str):
        text = ""
    sources = payload.get("sources", [])
    aliases = {identifier: fixture_id for fixture_id, identifier in identifiers.items()}
    retrieved = sorted({aliases.get(source.get("record_id"), "unknown") for source in sources})
    checks = automatic_checks(case, response.status_code, text, measured.calls, retrieved)
    return CaseResult(
        case_id=case.id, outcome="request_failed" if response.is_error else "completed",
        http_status=response.status_code, response=text, duration_ms=elapsed,
        setup_duration_ms=setup_ms,
        calls=measured.calls, setup_calls=setup_calls, checks=checks,
        retrieved_documents=retrieved, sources=sources, permitted_material=material,
    )


def run_case(case, backend, model, embedding_model, trace_timings=None):
    with TemporaryDirectory(prefix="lumen-evaluation-") as directory:
        app = create_app(Path(directory))
        measured = MeasuredModel(backend)
        app.state.lumen.model = measured
        with TestClient(app, base_url="http://127.0.0.1:8765", raise_server_exceptions=False) as client:
            setup_started = time.perf_counter()
            setup_started_at = datetime.now(UTC).isoformat()
            try:
                identifiers = prepare_case(client, case, model, embedding_model)
            except SetupFailure as exc:
                if trace_timings is not None:
                    trace_timings[case.id] = {
                        "phase": "setup", "started_at": setup_started_at,
                        "ended_at": datetime.now(UTC).isoformat(), "calls": measured.timings,
                    }
                return CaseResult(
                    case_id=case.id, outcome="setup_failed", http_status=exc.status,
                    response=str(exc), duration_ms=0.0, calls=[], setup_calls=measured.calls,
                    setup_duration_ms=round((time.perf_counter() - setup_started) * 1000, 3),
                    checks={"setup_completed": False}, retrieved_documents=[], sources=[],
                    permitted_material=[],
                )
            material = permitted_material(app.state.lumen, identifiers)
            setup_ms = round((time.perf_counter() - setup_started) * 1000, 3)
            setup_calls = measured.calls
            measured.calls = []
            measured.timings = []
            measured.forbidden_markers = case.forbidden_input_markers
            started = time.perf_counter()
            started_at = datetime.now(UTC).isoformat()
            response = execute_case(client, case, identifiers)
            elapsed = round((time.perf_counter() - started) * 1000, 3)
            if trace_timings is not None:
                trace_timings[case.id] = {
                    "phase": "request", "started_at": started_at,
                    "ended_at": datetime.now(UTC).isoformat(), "calls": measured.timings,
                }
            return collect_result(
                case, response, elapsed, measured, setup_calls, setup_ms, material, identifiers,
            )


def source_fingerprints():
    paths = ["lumen/app.py", "lumen/documents.py", "lumen/inference.py", "lumen/storage.py",
             "lumen/evaluation.py", "lumen/evaluation_scoring.py", "lumen/langsmith_export.py",
             "scripts/evaluate.py"]
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}


def run_evaluation(dataset, dataset_sha256, backend, *, model, embedding_model="", mode,
                   model_identity=None, trace_timings=None):
    fingerprints = source_fingerprints()
    results = [run_case(case, backend, model, embedding_model, trace_timings)
               for case in dataset.cases]
    return EvaluationReport(
        run_id=secrets.token_hex(16), created_at=datetime.now(UTC).isoformat(), mode=mode,
        dataset_id=dataset.dataset_id, dataset_version=dataset.version,
        dataset_sha256=dataset_sha256, evaluator_version=EVALUATOR_VERSION,
        model=model, embedding_model=embedding_model, model_identity=model_identity or {},
        source_fingerprints=fingerprints, sources_unchanged=fingerprints == source_fingerprints(),
        environment={"python": platform.python_version(),
                     **{name: version(name) for name in ("fastapi", "pydantic", "httpx")}},
        results=results,
    )
