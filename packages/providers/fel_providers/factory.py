"""Environment-driven provider selection (ADR-0012, issue #195).

Two builders, both pure functions of an environment mapping so a caller can pass
``os.environ`` in a process and a dict in a test:

* :func:`build_structured_llm_provider` — ``FEL_LLM_PROVIDER`` in
  ``{mock, openai, anthropic}``, default ``openai`` (ADR-0002's pin remains the
  default value of the knob until the #177/#132 benchmark records an amendment).
* :func:`build_embedding_provider` — ``FEL_EMBEDDING_PROVIDER`` in
  ``{mock, openai}``, default ``openai``. Anthropic ships no embeddings
  endpoint, so it is not a legal value.

Fail-closed rules, mirroring ``fel_workers.__main__``:

* Mode values are parsed strictly (:func:`read_mode_flag`): ``1/true/yes/on``
  (case-insensitive) means set, absent/empty means unset, and any other spelling
  is a ``ProviderConfigurationError`` naming the variable. ``0``/``false`` are
  rejected rather than treated as unset — the way to unset a mode is to remove
  the variable, so an operator who believes a flag is configured never gets the
  "unconfigured" branch by accident.
* **The mocks are never implicit.** ``FEL_LLM_PROVIDER=mock`` binds a model that
  fabricates complete financial output; it is refused unless ``FEL_ALLOW_MOCK_LLM``
  is *also* set, which is the existing opt-in the worker entrypoint enforces.
  ``FEL_EMBEDDING_PROVIDER=mock`` reuses the same opt-in rather than inventing a
  second variable: a mock index is fabricated vectors, and a run built on one is
  as unfit for a tenant as fabricated claims.
* A live selection with no key is a ``ProviderConfigurationError``. Keys come
  from ``FEL_OPENAI_API_KEY`` / ``FEL_ANTHROPIC_API_KEY`` only — never from a
  parameter, a config file, or a payload — and their values are never echoed in
  an error message.

Base URLs are deliberately not configurable from the environment: the key is
attached to the request, so an environment-supplied host would be a credential
exfiltration path. Tests construct adapters directly with an ``httpx``
``MockTransport``.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from fel_providers.anthropic_live import DEFAULT_MODEL as DEFAULT_ANTHROPIC_MODEL
from fel_providers.anthropic_live import AnthropicStructuredProvider
from fel_providers.interfaces import EmbeddingProvider, StructuredLLMProvider
from fel_providers.live_http import LiveHttpConfig, ProviderConfigurationError
from fel_providers.mocks import MockEmbeddingProvider, MockStructuredLLMProvider
from fel_providers.openai_live import (
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_DIMENSIONS,
    OpenAIEmbeddingProvider,
    OpenAIStructuredProvider,
)
from fel_providers.openai_live import DEFAULT_MODEL as DEFAULT_OPENAI_MODEL

LLM_PROVIDER_ENV = "FEL_LLM_PROVIDER"
EMBEDDING_PROVIDER_ENV = "FEL_EMBEDDING_PROVIDER"
ALLOW_MOCK_ENV = "FEL_ALLOW_MOCK_LLM"
OPENAI_KEY_ENV = "FEL_OPENAI_API_KEY"
ANTHROPIC_KEY_ENV = "FEL_ANTHROPIC_API_KEY"

LLM_PROVIDERS = frozenset({"mock", "openai", "anthropic"})
EMBEDDING_PROVIDERS = frozenset({"mock", "openai"})
DEFAULT_LLM_PROVIDER = "openai"
DEFAULT_EMBEDDING_PROVIDER = "openai"

_TRUTHY_FLAG_VALUES = frozenset({"1", "true", "yes", "on"})


def read_mode_flag(env: Mapping[str, str], name: str) -> bool:
    """Strict boolean mode flag; unrecognized spellings fail closed."""
    raw = env.get(name)
    if raw is None:
        return False
    value = raw.strip()
    if not value:
        return False
    if value.lower() in _TRUTHY_FLAG_VALUES:
        return True
    raise ProviderConfigurationError(
        f"{name} has unrecognized value {raw!r} — expected 1/true/yes/on"
        " (case-insensitive) or unset (remove the variable)."
    )


def _selection(env: Mapping[str, str], name: str, *, default: str, allowed: frozenset[str]) -> str:
    raw = env.get(name, "").strip().lower()
    if not raw:
        return default
    if raw not in allowed:
        raise ProviderConfigurationError(
            f"{name}={raw!r} is not one of {sorted(allowed)}",
        )
    return raw


def _require_key(env: Mapping[str, str], name: str) -> str:
    key = env.get(name, "").strip()
    if not key:
        raise ProviderConfigurationError(
            f"{name} is not set — refusing to start a live provider without a credential."
        )
    return key


def _require_mock_opt_in(env: Mapping[str, str], *, what: str) -> None:
    if not read_mode_flag(env, ALLOW_MOCK_ENV):
        raise ProviderConfigurationError(
            f"{what} selects the deterministic MOCK provider, which fabricates output."
            f" Set {ALLOW_MOCK_ENV}=1 to opt in explicitly (non-production only)."
        )


def _http_config(env: Mapping[str, str]) -> LiveHttpConfig:
    return LiveHttpConfig(
        timeout_seconds=_float(env, "FEL_LLM_TIMEOUT_SECONDS", 60.0),
        max_retries=_int(env, "FEL_LLM_MAX_RETRIES", 3),
        min_interval_seconds=_float(env, "FEL_LLM_MIN_INTERVAL_SECONDS", 0.0),
    )


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ProviderConfigurationError(f"{name}={raw!r} is not a number") from exc


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ProviderConfigurationError(f"{name}={raw!r} is not an integer") from exc


def _decimal(env: Mapping[str, str], name: str) -> Decimal:
    raw = env.get(name, "").strip()
    if not raw:
        return Decimal("0")
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ProviderConfigurationError(f"{name}={raw!r} is not a decimal") from exc


def build_structured_llm_provider(env: Mapping[str, str]) -> StructuredLLMProvider:
    """Bind the ``StructuredLLMProvider`` selected by ``FEL_LLM_PROVIDER``."""
    selection = _selection(
        env, LLM_PROVIDER_ENV, default=DEFAULT_LLM_PROVIDER, allowed=LLM_PROVIDERS
    )
    if selection == "mock":
        _require_mock_opt_in(env, what=f"{LLM_PROVIDER_ENV}=mock")
        return MockStructuredLLMProvider()
    config = _http_config(env)
    input_price = _decimal(env, "FEL_LLM_INPUT_USD_PER_MTOK")
    output_price = _decimal(env, "FEL_LLM_OUTPUT_USD_PER_MTOK")
    if selection == "anthropic":
        return AnthropicStructuredProvider(
            api_key=_require_key(env, ANTHROPIC_KEY_ENV),
            model=env.get("FEL_ANTHROPIC_MODEL", "").strip() or DEFAULT_ANTHROPIC_MODEL,
            config=config,
            input_usd_per_mtok=input_price,
            output_usd_per_mtok=output_price,
        )
    return OpenAIStructuredProvider(
        api_key=_require_key(env, OPENAI_KEY_ENV),
        model=env.get("FEL_OPENAI_MODEL", "").strip() or DEFAULT_OPENAI_MODEL,
        config=config,
        use_chat_completions=read_mode_flag(env, "FEL_OPENAI_USE_CHAT_COMPLETIONS"),
        input_usd_per_mtok=input_price,
        output_usd_per_mtok=output_price,
    )


def build_embedding_provider(env: Mapping[str, str]) -> EmbeddingProvider:
    """Bind the ``EmbeddingProvider`` selected by ``FEL_EMBEDDING_PROVIDER``."""
    selection = _selection(
        env,
        EMBEDDING_PROVIDER_ENV,
        default=DEFAULT_EMBEDDING_PROVIDER,
        allowed=EMBEDDING_PROVIDERS,
    )
    if selection == "mock":
        _require_mock_opt_in(env, what=f"{EMBEDDING_PROVIDER_ENV}=mock")
        return MockEmbeddingProvider(dimensions=EMBEDDING_DIMENSIONS)
    return OpenAIEmbeddingProvider(
        api_key=_require_key(env, OPENAI_KEY_ENV),
        model=env.get("FEL_OPENAI_EMBEDDING_MODEL", "").strip() or DEFAULT_EMBEDDING_MODEL,
        dimensions=EMBEDDING_DIMENSIONS,
        config=_http_config(env),
    )


__all__ = [
    "ALLOW_MOCK_ENV",
    "ANTHROPIC_KEY_ENV",
    "DEFAULT_EMBEDDING_PROVIDER",
    "DEFAULT_LLM_PROVIDER",
    "EMBEDDING_PROVIDERS",
    "EMBEDDING_PROVIDER_ENV",
    "LLM_PROVIDERS",
    "LLM_PROVIDER_ENV",
    "OPENAI_KEY_ENV",
    "build_embedding_provider",
    "build_structured_llm_provider",
    "read_mode_flag",
]
