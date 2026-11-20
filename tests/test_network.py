import asyncio
import json

import httpx
import pytest

from lumen import inference, research
from lumen.inference import LocalModel, ModelError


def mock_client(monkeypatch, module, handler):
    original = httpx.AsyncClient
    calls = []

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        calls.append(kwargs)
        return original(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(module.httpx, "AsyncClient", client)
    return calls


def test_model_uses_only_loopback_and_blocks_remote_metadata(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "127.0.0.1"
        assert request.url.port == 11434
        return httpx.Response(200, json={"remote_host": "https://cloud.example"})

    mock_client(monkeypatch, inference, handler)
    with pytest.raises(ModelError, match="Hosted"):
        asyncio.run(LocalModel().generate("local-model", "Answer", {"question": "Hello"}))
    assert len(requests) == 1
    with pytest.raises(ModelError):
        asyncio.run(LocalModel().generate("qwen:cloud", "Answer", {}))
    assert len(requests) == 1


def test_model_success_and_incomplete_output_failure(monkeypatch):
    incomplete = False

    def handler(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {"llama.context_length": 8192}})
        return httpx.Response(
            200,
            json={
                "message": {"content": "A local answer."},
                "done_reason": "length" if incomplete else "stop",
            },
        )

    mock_client(monkeypatch, inference, handler)
    assert asyncio.run(LocalModel().generate("local", "Answer", {})) == "A local answer."
    incomplete = True
    with pytest.raises(ModelError, match="output limit"):
        asyncio.run(LocalModel().generate("local", "Answer", {}))
    with pytest.raises(ModelError, match="context budget"):
        asyncio.run(LocalModel().generate("local", "Answer", {"question": "x" * 10000}))


def test_model_list_filters_hosted_models(monkeypatch):
    def handler(request):
        if request.url.path == "/api/show":
            capability = (
                "embedding" if json.loads(request.content)["model"] == "embed:latest"
                else "completion"
            )
            return httpx.Response(200, json={"capabilities": [capability]})
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "local:latest"},
                    {"name": "embed:latest"},
                    {"name": "model:cloud"},
                    {"name": "remote", "remote_host": "https://cloud.test"},
                ]
            },
        )

    mock_client(monkeypatch, inference, handler)
    assert asyncio.run(LocalModel().models()) == ["local:latest"]


def test_embeddings_are_local_untruncated_and_block_remote_metadata(monkeypatch):
    remote = False
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "127.0.0.1" and request.url.port == 11434
        if request.url.path == "/api/show":
            return httpx.Response(
                200, json={"capabilities": ["embedding"], "remote_host": "cloud" if remote else ""}
            )
        assert request.url.path == "/api/embed"
        assert json.loads(request.content) == {
            "model": "local-embed", "input": ["synthetic"], "truncate": False
        }
        return httpx.Response(200, json={"embeddings": [[0.5, 0.2]]})

    mock_client(monkeypatch, inference, handler)
    assert asyncio.run(LocalModel().embed("local-embed", ["synthetic"])) == [[0.5, 0.2]]
    remote = True
    with pytest.raises(ModelError, match="Hosted"):
        asyncio.run(LocalModel().embed("local-embed", ["private"]))
    assert len(requests) == 3


@pytest.mark.parametrize(
    "vectors",
    [[], [[0, 0]], [[True, 1]], [["bad", 1]], [[1, 0], [1, 0]], [[None, 1]]],
)
def test_invalid_embeddings_fail_explicitly(monkeypatch, vectors):
    def handler(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["embedding"]})
        return httpx.Response(200, json={"embeddings": vectors})

    mock_client(monkeypatch, inference, handler)
    with pytest.raises(ModelError, match="invalid"):
        asyncio.run(LocalModel().embed("local-embed", ["synthetic"]))


def test_brave_uses_fixed_destination_and_only_approved_query(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url).startswith(research.BRAVE_URL)
        assert request.url.params["q"] == "public query"
        assert request.headers["X-Subscription-Token"] == "test-key"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Valid",
                            "url": "https://example.test/page",
                            "description": "Public snippet",
                        },
                        {"title": "Injection", "url": "javascript:alert(1)", "description": "Bad"},
                    ]
                }
            },
        )

    calls = mock_client(monkeypatch, research, handler)
    sources = asyncio.run(research.search("public query", "test-key"))
    assert len(sources) == 1
    assert sources[0]["citation"] == "W1"
    assert len(requests) == 1
    assert calls[0]["follow_redirects"] is False


def test_brave_network_errors_report_uncertain_delivery(monkeypatch):
    def handler(request):
        return httpx.Response(429, json={"error": "quota"})

    mock_client(monkeypatch, research, handler)
    with pytest.raises(research.ResearchError, match="may have reached Brave"):
        asyncio.run(research.search("public query", "test-key"))
