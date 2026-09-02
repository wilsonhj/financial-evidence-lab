# ADR-0012: Provider-agnostic structured-output layer

**Status:** Accepted
**Date:** 2026-09-02
**Accepted:** 2026-09-02 by the integration lead on branch `claude/repo-analysis-improvements-m25v4u` (review #188). The provider pin itself remains open until the #177 / #132 benchmark records Amendment 1; what is accepted is the layer, the selection knobs, and the fail-closed rules.
**Issues:** #195 (this ADR), #193 (claims-output consumer), #194 (extraction tool loop), #177 / #132 (benchmark)
**Amends:** ADR-0002 (AI and retrieval section)

## Context

Three facts about `main` conflict.

1. ADR-0002 (Accepted) pins "OpenAI for generation" and `text-embedding-3`
   embeddings truncated to <= 512 dimensions.
2. Issue #132 directs generation and verification at a Claude model, and notes
   that Anthropic ships no embeddings endpoint.
3. No live adapter exists for either provider. `packages/providers/fel_providers/mocks.py`
   holds the only `StructuredLLMProvider`, and `interfaces.py` still says
   "M3-CONTRACT ships mock only". Workers bind the mock only under
   `FEL_ALLOW_MOCK_LLM`, so a production worker without that flag refuses to
   start — correct, but it means extraction and reading cannot run anywhere.

Constitution principle V requires benchmark evidence and an accepted ADR for any
provider substitution, and ADR-0002's change rule requires evidence that the
current default fails a requirement. Spec 004 finding A-1 records the
contradiction; no ADR resolves it. Deciding the pin *now*, before the #177/#132
benchmark exists, would be exactly the unevidenced substitution principle V
forbids — but leaving the repository with no live adapter at all is not a
neutral position either.

## Decision

Resolve the conflict by making provider identity a **configured selection behind
the existing frozen protocols**, and defer the pin to the benchmark.

1. **Keep the frozen protocols.** `StructuredLLMProvider`, `EmbeddingProvider`
   and `StructuredModelResult` in `fel_providers/interfaces.py` are unchanged.
   Every adapter is an implementation of them; no caller learns which provider
   it holds.
2. **Add live adapters behind those protocols**, each a thin `httpx` client with
   an injectable transport/clock (the `fel_workers.http.ThrottledRetryingClient`
   pattern), not a vendor SDK:
   - `openai_live.OpenAIStructuredProvider` — Responses API,
     `text.format = {"type": "json_schema", "strict": true, ...}`; a Chat
     Completions `response_format` path behind `use_chat_completions` as a
     fallback, not the default.
   - `openai_live.OpenAIEmbeddingProvider` — `POST /v1/embeddings` with
     `dimensions=512`, enforced on the response as well as the request because
     `halfvec(512)` is a storage contract.
   - `anthropic_live.AnthropicStructuredProvider` — Messages API with a **single
     forced tool** whose `input_schema` is the request's JSON Schema
     (`tool_choice: {"type": "tool", ...}`, `strict: true`), which is the
     documented route to schema-conformant JSON. Generation only: Anthropic has
     no embeddings endpoint, so no embedding adapter can exist for it.
3. **Selection by environment**, via `fel_providers.factory`:
   `FEL_LLM_PROVIDER={mock,openai,anthropic}` and
   `FEL_EMBEDDING_PROVIDER={mock,openai}`, both defaulting to `openai`. The
   default is what keeps ADR-0002 satisfied: OpenAI remains the pinned default
   value of the knob, and anything else is an explicit operator decision.
4. **The mocks stay fail-closed.** Selecting either mock additionally requires
   the existing `FEL_ALLOW_MOCK_LLM` opt-in, with the same strict flag parsing
   the worker entrypoint uses (`1/true/yes/on`; `0`/`false` rejected rather than
   read as "unset"). A mock model fabricates complete financial output and a
   mock index fabricates vectors; neither may ever be reached implicitly.
5. **The final pin is decided by the #177/#132 benchmark** and recorded here as
   *Amendment 1* to this ADR, with the measured numbers. Until then this ADR
   changes no default and substitutes no provider — it makes substitution
   *possible to measure*.
6. **The extraction tool loop is deferred** (issue #194). The adapters implement
   single-shot schema-constrained generation, which is what every current role
   needs; a multi-turn tool loop is added when a live adapter first needs one,
   not speculatively.

ADR-0002 is not rewritten. It carries a one-paragraph "Amended by ADR-0012" note
at the top; its body stays the historical record.

### Configuration surface

| Variable | Values | Default | Note |
|---|---|---|---|
| `FEL_LLM_PROVIDER` | `mock` / `openai` / `anthropic` | `openai` | Unknown value fails closed |
| `FEL_EMBEDDING_PROVIDER` | `mock` / `openai` | `openai` | `anthropic` is not legal — no endpoint |
| `FEL_ALLOW_MOCK_LLM` | `1/true/yes/on` | unset | Required for either mock selection |
| `FEL_OPENAI_API_KEY` / `FEL_ANTHROPIC_API_KEY` | secret | unset | Only source of a key |
| `FEL_OPENAI_MODEL` / `FEL_ANTHROPIC_MODEL` / `FEL_OPENAI_EMBEDDING_MODEL` | model id | per-adapter default | Pinned into runs and index versions as today |
| `FEL_OPENAI_USE_CHAT_COMPLETIONS` | flag | unset | Fallback endpoint |
| `FEL_LLM_TIMEOUT_SECONDS` / `FEL_LLM_MAX_RETRIES` / `FEL_LLM_MIN_INTERVAL_SECONDS` | numbers | 60 / 3 / 0 | Transport bounds |
| `FEL_LLM_INPUT_USD_PER_MTOK` / `FEL_LLM_OUTPUT_USD_PER_MTOK` | decimals | 0 | Feeds `estimated_cost_usd`; prices are configuration, never hard-coded |

Base URLs are deliberately **not** configurable from the environment: the key
travels with the request, so an environment-supplied host would be a credential
exfiltration path. Tests inject an `httpx.MockTransport` directly.

### Failure and refusal policy (identical across adapters)

- `429` and `5xx` are retried a bounded number of times with exponential
  backoff, honouring `Retry-After` clamped to 60 s so a hostile or mistaken
  header cannot park a worker. Transport errors retry the same way.
- Any other `4xx` fails hard: a bad key or a bad model id does not become valid
  by waiting.
- A provider refusal (Anthropic `stop_reason == "refusal"`, OpenAI's refusal
  content block / `message.refusal`) maps to
  `StructuredModelResult(refused=True, parsed=None)` — a recorded outcome, never
  an exception and never an empty answer that reads like a real one.
- Output that is not JSON, or is JSON that fails the requested schema, raises a
  typed `ProviderProtocolError`. There is no lenient parse and no free-text
  fallback.
- Usage (`input_tokens` / `output_tokens`) is read from the provider's own usage
  object and populated on every result, refusals included, so the run's budget
  record is complete.

## Security posture

- **Keys from the environment only** (`FEL_OPENAI_API_KEY`,
  `FEL_ANTHROPIC_API_KEY`), read in the factory and passed to the adapter. No
  adapter reads the environment, accepts a key in a payload, or writes one to a
  result. No error message echoes a key value.
- **No prompt or completion text in logs or exceptions.** Adapter exceptions
  carry the status code, the attempt count, the provider request id and a schema
  path — never a request body, a response body, or a model string. This is the
  same rule `workers/src/fel_workers/redact.py` enforces at the durable-error
  sinks; the adapters keep the text out of the exception in the first place, so
  redaction is a second line of defence rather than the only one.
- The short categorical refusal string is carried on the result because the
  protocol requires it (and Anthropic's is reduced to `refusal:<category>` from
  `stop_details`); the modules never log it.
- Model output is data. It is validated against the requested schema before any
  caller sees it, and the reader (#193) additionally refuses citations to items
  outside the selected context.

## Consequences

- Extraction and reading can run live for the first time, on either provider,
  without a code change and without touching a caller.
- CI stays offline: every adapter test drives a recorded `httpx.MockTransport`
  with a fake clock.
- The benchmark (#177/#132) now has two comparable implementations to measure
  instead of a choice made on paper.
- Two live paths mean two shapes to keep working; the shared
  `live_http.RetryingJsonClient` keeps the retry/refusal/redaction policy in one
  place rather than per adapter.
- `estimated_cost_usd` is zero unless the price knobs are configured, so cost
  accounting is opt-in until an operator supplies current prices. This is
  deliberate: a hard-coded price table goes stale silently.
- Anthropic's absence of an embeddings endpoint means a Claude generation pin
  still leaves OpenAI in the stack for embeddings; "one provider" is not on the
  table for this MVP.

## Revisit triggers

| Trigger | Action |
|---|---|
| #177/#132 benchmark completes | Record the pin as Amendment 1 with the measured quality/cost/latency numbers; change the default only there |
| A live adapter needs multi-turn tool use for an extraction role | Implement the tool loop under #194; until then the single forced-tool call stands |
| A provider changes its structured-output surface (endpoint, field, or strict-mode rules) | Update that adapter only; the protocols and callers do not move |
| Refusal rate or schema-invalid rate on live traffic exceeds the run budget's tolerance | Treat as a prompt/schema defect first (contract error rates are recorded per run), not a provider swap |
| A third generation provider is proposed | New ADR with benchmark evidence per principle V; the factory's closed value set is the enforcement point |
| Embedding width must change from 512 | Contract change: `halfvec(512)`, the index version, and ADR-0002 all move together |

## Rejected alternatives

- **Rewrite ADR-0002 to name a provider now.** That is the unevidenced
  substitution principle V forbids; the benchmark does not exist yet.
- **Vendor SDKs.** They bring transitive dependencies, their own retry and
  logging behaviour (including request/response logging), and no injectable
  transport; the repo already has a fixture-transport HTTP pattern that keeps CI
  offline.
- **Provider-specific interfaces at the call sites.** Callers would learn which
  provider they hold, and the benchmark would compare two pipelines instead of
  two adapters.
- **Free-text parsing with a JSON "best effort" fallback.** A tolerated
  malformed answer is a fabricated answer; both adapters fail closed instead.
- **A per-provider embedding abstraction that fakes Anthropic embeddings** (e.g.
  by routing to OpenAI under an Anthropic selection). It would hide a second
  vendor and a second key behind a name that says otherwise.

## Verification

- Adapter contract suites, offline, per provider: schema-valid happy path,
  refusal, 429-then-success with `Retry-After` honoured, non-retryable 4xx not
  retried, malformed JSON, schema-invalid output, and (embeddings) a dimension
  mismatch and an input/vector count mismatch.
- Factory suite: default is OpenAI, unknown selections rejected, missing key
  fails closed, each mock requires `FEL_ALLOW_MOCK_LLM`, falsy flag spellings
  rejected, and no configuration error echoes a key value.
- Assertions that no exception message contains prompt or completion text.
- Acceptance for the pin (Amendment 1) is the #177/#132 benchmark, not this ADR.
