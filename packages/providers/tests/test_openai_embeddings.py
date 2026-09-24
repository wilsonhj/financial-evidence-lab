"""Offline transport contract for the explicit-key embeddings adapter."""

import json
from decimal import Decimal

import httpx
import pytest

from fel_providers.openai_embeddings import OpenAIEmbeddingProvider


def test_indexed_batch_and_usage():
    seen = []
    usage = []

    def handle(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "text-embedding-3-small",
                "data": [
                    {"object": "embedding", "index": i, "embedding": [i + 1.0] * 512}
                    for i in (1, 0)
                ],
                "usage": {"prompt_tokens": 7, "total_tokens": 7},
            },
        )

    provider = OpenAIEmbeddingProvider(
        api_key="test-secret",
        model="text-embedding-3-small",
        price_per_million_tokens=Decimal("0.02"),
        usage_sink=usage.append,
        transport=httpx.MockTransport(handle),
    )
    assert provider.embed(["first", "second"]) == [[1.0] * 512, [2.0] * 512]
    assert len(seen) == len(usage) == 1
    assert json.loads(seen[0].content) == {
        "model": "text-embedding-3-small",
        "input": ["first", "second"],
        "encoding_format": "float",
        "dimensions": 512,
    }
    assert str(seen[0].url) == "https://api.openai.com/v1/embeddings"
    assert usage[0].input_tokens == 7
    assert usage[0].estimated_cost_usd == Decimal("0.00000014")


def response_body():
    return {
        "object": "list",
        "model": "text-embedding-3-small",
        "data": [{"object": "embedding", "index": 0, "embedding": [1.0] * 512}],
        "usage": {"prompt_tokens": 7, "total_tokens": 7},
    }


def make_provider(handler, usage, **kwargs):
    return OpenAIEmbeddingProvider(
        api_key="private-key-canary",
        model="text-embedding-3-small",
        price_per_million_tokens=Decimal("0.02"),
        usage_sink=usage.append,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(model="hostile-provider-text"),
        lambda d: d.update(object="wrong"),
        lambda d: d.update(data=[]),
        lambda d: d["data"].append(d["data"][0]),
        lambda d: d["data"][0].update(index=True),
        lambda d: d["data"][0].update(index=-1),
        lambda d: d["data"][0].update(index=1),
        lambda d: d["data"][0].update(object="wrong"),
        lambda d: d["data"][0].update(embedding=[1.0] * 511),
        lambda d: d["data"][0].update(embedding=[0.0] * 512),
        lambda d: d["data"][0].update(embedding=[True] * 512),
        lambda d: d["data"][0].update(embedding=["hostile-provider-text"] * 512),
        lambda d: d["data"][0].update(embedding=[10**400] * 512),
    ],
)
def test_malformed_billable_result_preserves_known_usage(mutation):
    from fel_providers.openai_embeddings import OpenAIEmbeddingError

    data = response_body()
    mutation(data)
    usage = []
    provider = make_provider(lambda r: httpx.Response(200, json=data), usage)
    with pytest.raises(OpenAIEmbeddingError) as caught:
        provider.embed(["private-input-canary"])
    assert caught.value.code == "invalid_response"
    assert caught.value.usage == usage[0]
    assert usage[0].input_tokens == 7
    assert caught.value.__context__ is None
    assert "hostile-provider-text" not in str(caught.value)


@pytest.mark.parametrize(
    "raw_usage",
    [
        None,
        {},
        {"prompt_tokens": 7},
        {"prompt_tokens": -1, "total_tokens": -1},
        {"prompt_tokens": True, "total_tokens": 1},
        {"prompt_tokens": 1, "total_tokens": True},
        {"prompt_tokens": 7, "total_tokens": 8},
        {"prompt_tokens": 0, "total_tokens": 0},
        {"prompt_tokens": "7", "total_tokens": 7},
        {"prompt_tokens": 300001, "total_tokens": 300001},
    ],
)
def test_unknown_usage_is_not_zero(raw_usage):
    from fel_providers.openai_embeddings import OpenAIEmbeddingError

    data = response_body()
    data["usage"] = raw_usage
    usage = []
    with pytest.raises(OpenAIEmbeddingError) as caught:
        make_provider(lambda r: httpx.Response(200, json=data), usage).embed(["input"])
    assert usage[0].input_tokens is None
    assert usage[0].estimated_cost_usd is None
    assert caught.value.usage == usage[0]


@pytest.mark.parametrize(
    "body",
    [
        b"private-key-canary",
        b'{"usage":{},"usage":{}}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":-Infinity}',
        b"[]",
        b'{"nested":{"key":1,"key":2}}',
        b"\xff",
    ],
)
def test_strict_json_and_safe_diagnostics(body):
    from fel_providers.openai_embeddings import OpenAIEmbeddingError

    usage = []
    with pytest.raises(OpenAIEmbeddingError) as caught:
        make_provider(lambda r: httpx.Response(200, content=body), usage).embed(["input"])
    assert caught.value.__context__ is None
    assert "private-key-canary" not in repr(caught.value)
    assert usage[0].total_tokens is None


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500, 503])
def test_http_errors_never_retry_or_forward_bodies(status):
    from fel_providers.openai_embeddings import OpenAIEmbeddingError

    calls, usage = [], []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            status,
            content=b"private-key-canary",
            headers={"location": "https://evil.invalid", "retry-after": "0"},
        )

    with pytest.raises(OpenAIEmbeddingError) as caught:
        make_provider(handle, usage).embed(["input"])
    assert len(calls) == len(usage) == 1
    assert caught.value.code == "http_error"
    assert caught.value.usage.status_code == status
    assert caught.value.__context__ is None
    assert "private-key-canary" not in str(caught.value)


def test_hostile_network_exception_not_chained():
    from fel_providers.openai_embeddings import OpenAIEmbeddingError

    calls, usage = [], []

    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout("private-key-canary private-input-canary", request=request)

    with pytest.raises(OpenAIEmbeddingError) as caught:
        make_provider(handle, usage).embed(["input"])
    assert len(calls) == len(usage) == 1
    assert caught.value.code == "transport_error"
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None


def test_sink_failure_retains_usage_without_exception_context():
    from fel_providers.openai_embeddings import OpenAIEmbeddingError

    def sink(usage):
        raise RuntimeError("private-key-canary")

    provider = OpenAIEmbeddingProvider(
        api_key="test",
        model="text-embedding-3-small",
        price_per_million_tokens=Decimal("1"),
        usage_sink=sink,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response_body())),
    )
    with pytest.raises(OpenAIEmbeddingError) as caught:
        provider.embed(["input"])
    assert caught.value.code == "usage_sink_failed"
    assert caught.value.usage.input_tokens == 7
    assert caught.value.__context__ is None
    assert "private-key-canary" not in str(caught.value)


def test_response_limit_and_encoding():
    from fel_providers.openai_embeddings import OpenAIEmbeddingError

    for response, code in [
        (httpx.Response(200, content=b"x" * 100), "response_too_large"),
        (httpx.Response(200, headers={"content-encoding": "unknown"}), "invalid_encoding"),
    ]:
        usage = []
        with pytest.raises(OpenAIEmbeddingError) as caught:
            make_provider(lambda r, result=response: result, usage, max_response_bytes=99).embed(
                ["input"]
            )
        assert caught.value.code == code
        assert usage[0].input_tokens is None


@pytest.mark.parametrize(
    "texts",
    [
        None,
        "text",
        [""],
        [True],
        ["\ud800"],
        ["x" * 8193],
        ["x"] * 65,
        ["x" * 8192] * 16,
        ["\x01" * 8192] * 15,
    ],
)
def test_invalid_input_never_calls(texts):
    from fel_providers.openai_embeddings import OpenAIEmbeddingError

    usage = []

    def handle(request):
        pytest.fail("network call on invalid input")

    with pytest.raises(OpenAIEmbeddingError, match="invalid_input"):
        make_provider(handle, usage).embed(texts)
    assert usage == []


def test_empty_and_no_environment_fallback(monkeypatch):
    from fel_providers.openai_embeddings import OpenAIEmbeddingError

    monkeypatch.setenv("OPENAI_API_KEY", "owner-key")
    monkeypatch.setenv("FEL_OPENAI_API_KEY", "owner-key")
    usage = []

    def handle(request):
        pytest.fail("network call for empty input")

    assert make_provider(handle, usage).embed([]) == []
    assert usage == []
    with pytest.raises(OpenAIEmbeddingError, match="invalid_configuration"):
        OpenAIEmbeddingProvider(
            api_key="",
            model="text-embedding-3-small",
            price_per_million_tokens=Decimal(1),
            usage_sink=usage.append,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("api_key", "line\nbreak"),
        ("api_key", "é"),
        ("model", "text-embedding-ada-002"),
        ("price_per_million_tokens", Decimal("NaN")),
        ("price_per_million_tokens", Decimal(-1)),
        ("price_per_million_tokens", 1.0),
        ("price_per_million_tokens", Decimal("1e-13")),
        ("timeout_seconds", float("inf")),
        ("timeout_seconds", True),
        ("timeout_seconds", 31),
        ("max_response_bytes", True),
        ("max_response_bytes", 0),
        ("usage_sink", None),
    ],
)
def test_config_validation(field, value):
    from fel_providers.openai_embeddings import OpenAIEmbeddingError

    args = dict(
        api_key="test",
        model="text-embedding-3-small",
        price_per_million_tokens=Decimal(".02"),
        usage_sink=lambda u: None,
    )
    args[field] = value
    with pytest.raises(OpenAIEmbeddingError, match="invalid_configuration"):
        OpenAIEmbeddingProvider(**args)


def test_duplicate_indexes_with_matching_count():
    from fel_providers.openai_embeddings import OpenAIEmbeddingError

    data = response_body()
    data["data"].append(data["data"][0])
    with pytest.raises(OpenAIEmbeddingError, match="invalid_response"):
        make_provider(lambda r: httpx.Response(200, json=data), []).embed(["a", "b"])


def test_exponent_overflow_vector_rejected_with_known_usage():
    from fel_providers.openai_embeddings import OpenAIEmbeddingError

    body = json.dumps(response_body()).replace("1.0", "1e999", 1)
    usage = []
    with pytest.raises(OpenAIEmbeddingError):
        make_provider(lambda r: httpx.Response(200, content=body), usage).embed(["input"])
    assert usage[0].input_tokens == 7


def test_slow_small_chunks_checked_without_buffering(monkeypatch):
    from fel_providers import openai_embeddings
    from fel_providers.openai_embeddings import OpenAIEmbeddingError

    clock = [0]
    consumed = []

    class Trickle(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(200):
                clock[0] += 1
                consumed.append(1)
                yield b" "

    monkeypatch.setattr(openai_embeddings.time, "monotonic", lambda: clock[0])
    usage = []
    with pytest.raises(OpenAIEmbeddingError) as caught:
        make_provider(lambda r: httpx.Response(200, stream=Trickle()), usage).embed(["input"])
    assert caught.value.code == "deadline_exceeded"
    assert len(consumed) == 61
    assert usage[0].input_tokens is None


def test_stream_size_bound_stops_reading():
    from fel_providers.openai_embeddings import OpenAIEmbeddingError

    consumed = []

    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(200):
                consumed.append(1)
                yield b"x" * 50

    with pytest.raises(OpenAIEmbeddingError) as caught:
        make_provider(
            lambda r: httpx.Response(200, stream=Chunks()), [], max_response_bytes=99
        ).embed(["input"])
    assert caught.value.code == "response_too_large"
    assert len(consumed) == 2


def test_client_disables_environment_redirects_and_uses_explicit_key(monkeypatch):
    calls = []
    original = httpx.Client

    def client(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setenv("HTTPS_PROXY", "http://evil.invalid:1")

    def handle(request):
        assert request.headers["authorization"] == "Bearer private-key-canary"
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, json=response_body())

    make_provider(handle, []).embed(["input"])
    assert calls[0]["trust_env"] is False
    assert calls[0]["follow_redirects"] is False
    assert calls[0]["timeout"] == 10.0
