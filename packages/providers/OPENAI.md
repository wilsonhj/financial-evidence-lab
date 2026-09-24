# Explicit OpenAI structured adapter

Issue #323 adds `fel_providers.openai_structured.OpenAIStructuredProvider` behind
`StructuredLLMProvider`. It is not selected by any API or worker default. No
live call or credential provisioning is included in this package.

Construct it with an explicitly resolved `api_key`, a dated model snapshot such
as `gpt-4.1-2025-04-14`, three finite nonnegative Decimal prices per million tokens
(input, cached input, output), and a required `validate_output(schema, parsed)`
callback. The model is an illustrative supported shape, not a deployment choice
or an assertion of current pricing. The caller selects and verifies its model
and prices. The callback must use the caller's established schema validator,
raise on mismatch, return exactly None on success, and not mutate its arguments.
The adapter does not implement a partial JSON Schema engine. Domain, citation,
temporal and financial checks remain mandatory at the existing caller boundary.

Requests use the fixed HTTPS `/v1/responses` endpoint with strict `text.format`
JSON schema, no tools, no streaming, `store=false`, and explicit output budget
(1–100,000 tokens). Input is limited to 2 MiB and 256 text messages. Only
system/developer/user/assistant roles are accepted. Temperature must be finite
between zero and two; choose a snapshot supporting this parameter and strict
structured output. Unsupported API parameters return a sanitized failure; the
adapter never silently changes model, schema or temperature.

HTTPX is lazy-imported from the already locked application runtime, so installing
or importing the standalone protocol/mock package does not require a new
package dependency. Invocation requires that runtime's HTTPX. Tests inject
`httpx.MockTransport`; normal construction supplies no transport. No environment
credential, proxy, alternate endpoint or owner-key fallback is read. There are
no automatic retries (including 429/5xx), no redirects, and a fresh HTTP client
is closed per call. An injected transport must support that lifecycle. HTTP
operations have 30-second limits (connect five seconds); streamed body checks
apply a 60-second elapsed budget and a 2 MiB default response cap (configurable
from 1 KiB to 8 MiB). These are bounded transport operations, not a hard process
wall-clock deadline: DNS, custom transports and a blocking read can overshoot
an elapsed check. Compressed responses are rejected.

Only a completed response with the exact requested model, valid usage and one
assistant text/refusal item succeeds. Reasoning items are ignored, never logged.
JSON duplicates, nonfinite numbers, malformed bodies, conflicting output,
incomplete/error responses and schema mismatch fail closed. A refusal returns
no parsed object and a fixed generic reason, retaining token usage and cost.
The response id is syntax-checked. Raw metadata contains only completion status
and cached-input token count, never the original HTTP response, refusal text,
prompt, credential or reasoning. The parsed result is the requested sensitive
application data and must not be treated as a safe diagnostic/log payload.

Cost is `(uncached_input * input_price + cached_input * cached_price +
output * output_price) / 1_000_000`, computed with an isolated Decimal context.
`OpenAIStructuredError` exposes safe code and optional input/output/cached counts
and estimated cost. Valid usage remains attached to billable failures after
response decoding. Missing, malformed or inconsistent usage, HTTP failures and
transport failures have **None** usage/cost, not zero: the caller must retain
its reservation and reconcile unknown spend. No unsuccessful call is evidence
of free inference. Price/model attribution is caller-pinned; a response model
mismatch fails and its estimate must be reconciled rather than treated as a
verified invoice. No provider balance or budget enforcement is claimed here.

Provider diagnostics and callback exceptions are discarded before raising a
fresh fixed-message exception, outside the exception handler. Normal traceback
formatting therefore does not chain HTTP request headers or hostile provider
messages. Do not enable traceback-local capture or log the adapter's private
attributes; Python object memory is not a secrets vault.

Offline verification:

```sh
python -m pytest packages/providers/tests
python -m mypy packages/providers/fel_providers/openai_structured.py
```

Primary API references consulted September 16, 2026:
[Responses](https://developers.openai.com/api/docs/guides/responses),
[Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
Live integration, BYOK resolution, admission budgets, durable metering and invoice
reconciliation remain #195/#191/#177 and the registered public-auth/BYOK plan.
