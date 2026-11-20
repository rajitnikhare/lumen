"""Run a synthetic retrieval comparison against local Ollama in an isolated vault."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from lumen.app import create_app


def run(model: str, embedding_model: str) -> list[dict]:
    results = []
    with TemporaryDirectory(prefix="lumen-retrieval-demo-") as directory:
        app = create_app(Path(directory))
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            client.headers["X-Lumen-CSRF"] = client.get("/api/session").json()["csrf"]

            def request(method, path, **kwargs):
                response = client.request(method, path, **kwargs)
                if response.is_error:
                    raise RuntimeError(f"{method} {path}: {response.status_code} {response.text}")
                response.raise_for_status()
                return response.json()

            request("POST", "/api/unlock", json={"passphrase": "synthetic demo passphrase"})
            request("PUT", "/api/settings", json={"model": model})
            document = request(
                "POST",
                "/api/documents?filename=household-guide.txt&authorized=true",
                content=b"Terminate unused memberships. Estimated monthly savings: USD 47.",
            )
            question = "How can I lower my bills? Reply in at most two sentences."

            def ask(stage):
                turn = request("POST", "/api/chat", json={"message": question})
                results.append(
                    {
                        "stage": stage,
                        "question": question,
                        "answer": turn["answer"],
                        "retrieval": turn["retrieval"],
                        "sources": turn["sources"],
                    }
                )
                return turn

            baseline = ask("keyword")
            if baseline["sources"]:
                raise RuntimeError("The synthetic baseline unexpectedly matched keywords.")
            request(
                "PUT", "/api/settings",
                json={"model": model, "embedding_model": embedding_model},
            )
            grounded = ask("semantic")
            if not grounded["sources"] or "47" not in grounded["answer"]:
                raise RuntimeError("The semantic answer did not use the synthetic savings figure.")
            if "[S1]" not in grounded["answer"]:
                raise RuntimeError("The semantic answer did not cite its evidence.")
            request("PUT", f"/api/access/document/{document['id']}", json={"authorized": False})
            revoked = ask("revoked")
            if revoked["sources"] or "47" in revoked["answer"]:
                raise RuntimeError("Revoked evidence was still supplied or its figure repeated.")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="llama3:latest")
    parser.add_argument("--embedding-model", default="nomic-embed-text")
    args = parser.parse_args()
    print(json.dumps(run(args.model, args.embedding_model), indent=2))


if __name__ == "__main__":
    main()
