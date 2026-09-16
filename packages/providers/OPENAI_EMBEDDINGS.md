# Explicit-key OpenAI embeddings adapter (#326)

This is an offline-tested provider implementation, not live wiring, BYOK storage,
provider promotion, index publication or benchmark acceptance. Import directly from
`fel_providers.openai_embeddings`; existing provider interfaces and exports are
unchanged. `embed(list[str]) -> list[list[float]]` preserves `EmbeddingProvider`.

Construct `OpenAIEmbeddingProvider` with an explicit user-authorized `api_key`,
`model` (`text-embedding-3-small` or `text-embedding-3-large`), finite nonnegative
`Decimal` `price_per_million_tokens` and mandatory `usage_sink` callback. Prices
are supplied by the caller, not hardcoded current vendor prices. The adapter
never reads keys or proxy configuration from the environment. Callers must enforce
user ownership, credential revocation, approved privacy policy and durable budget
admission **before** invoking it. No owner/project key fallback is permitted.

The adapter sends one POST to `https://api.openai.com/v1/embeddings`, requesting
512 dimensions and float encoding, with redirects and environment routing disabled.
No automatic retries, alternate endpoints, model fallback or batch splitting occurs.
A caller must not retry blindly after a transport or metering error: the attempted
call may already have incurred a charge. Credentials supplied to injected transports
are trusted by the caller; transports are for offline testing, not untrusted plugins.

## Limits and validation

- At most 64 nonempty strings, each at most 8,192 UTF-8 bytes; at most 128,000
  aggregate input bytes and 256,000 serialized request bytes. Byte caps are deliberately
  conservative and are not tokenization estimates. An empty list returns `[]` with
  no network or usage callback. Invalid input is rejected before a call.
- Per-operation HTTP timeout defaults to 10 seconds, configurable only within
  `(0, 30]`. A 60-second elapsed guard is checked on every raw response chunk;
  an in-progress read can additionally consume its bounded HTTP timeout. This is
  not a preemptive cancellation timer. Injected transports must honour timeouts.
- Uncompressed response body limit defaults to 2,000,000 bytes, configurable up to
  4,000,000. Compressed responses are rejected before decoding; identity encoding is
  explicitly requested. Oversized streams stop without consuming their remainder.
- Strict JSON rejects duplicate members and nonfinite constants. Results must have
  the requested model, list/embedding object tags, exactly one valid integer index
  per input, and 512 finite numeric, non-boolean coordinates. Zero vectors fail.
  Out-of-order results are reordered by their validated indexes.

## Usage and failures

`EmbeddingUsage` contains only pinned provider/model, input/total tokens, estimated
Decimal cost and HTTP status. The callback runs once per attempted request, including
failed responses and network failures. Missing or malformed usage is `None` (unknown),
never zero or free. Valid prompt/total counts must agree and be positive integers
within the documented request token ceiling. Pricing accepts at most 12 fractional
places, bounded to 0–1000 USD/million tokens; cost arithmetic uses a local Decimal
context independent of the caller's precision.

Known usage is delivered before vector validation, so a billable malformed vector
still carries its charge. Unparseable/oversized/duplicate JSON, missing usage and
HTTP errors remain unknown and require caller reconciliation. Never refund an
unknown attempt merely because no vectors were returned.

`OpenAIEmbeddingError.code` is a static classification. `.usage` preserves the
known or unknown attempted-call metadata; preflight errors have no usage. Callback
failure raises `usage_sink_failed` with metadata for reconciliation and does not
return vectors. The callback might have persisted before failing: use a caller-owned
idempotent ledger, not a second provider call. The adapter does not guarantee ledger
persistence. Exceptions do not chain transport, JSON or callback exceptions; no
upstream body, vectors, input or keys appear in adapter messages. Do not configure
traceback tooling to capture frame locals containing request data or credentials.

## Offline verification and source

```bash
python -m pytest packages/providers/tests/test_openai_embeddings.py -q
python -m mypy packages/providers/fel_providers/openai_embeddings.py
python -m ruff check packages/providers/fel_providers/openai_embeddings.py packages/providers/tests/test_openai_embeddings.py
python -m black --check packages/providers/fel_providers/openai_embeddings.py packages/providers/tests/test_openai_embeddings.py
```

Tests use `httpx.MockTransport` only: exact serialized request, reordered batch,
malformed indexes/vectors/JSON/usage, error status, hostile exceptions, callback
failure, bounded response/slow chunks, no retries/redirects/env fallback and input
limits. No live provider call or API key is needed.

Transport fields checked against the [official OpenAI embeddings API reference](https://developers.openai.com/api/reference/resources/embeddings/methods/create)
on September 16, 2026. Provider availability, usage pricing and privacy policy must
be rechecked by the live-integration owner; this module does not authorize spending.
