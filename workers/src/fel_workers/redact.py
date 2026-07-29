"""Shared redaction for error text that reaches durable storage.

Two sinks record raw exception text: ``jobs.error`` (queue.fail) and
``extraction_run_steps.error`` (a failed stage record). Both can carry
document-derived content, because normalizer and validator errors interpolate
the offending value -- ``f"cannot normalize raw_value {value!r}"`` embeds a
slice of a filing. That bypasses the redaction discipline the event payloads
already apply.

This lives outside ``fel_workers.extraction`` on purpose: ``queue`` is generic
job infrastructure and must not import from a single job kind's package.

Two rules, both needed:

* credential shapes (``key=value``, ``key: value``, ``Bearer <token>``) are
  masked wherever they appear;
* quoted runs are masked positionally, because filing content is quoted by
  ``{value!r}`` and looks nothing like a credential -- no keyword rule catches
  it.
"""

from __future__ import annotations

import re

MAX_ERROR_CHARS = 256
_TRUNCATED = "...[truncated]"

# The keyed form must swallow an optional scheme word before the value.
# Ordering the alternation does NOT fix this: in "Authorization: Bearer <tok>"
# the keyed branch matches at offset 0 and, with a bare `\S+` value, consumes
# only the word "Bearer" -- leaving the token in the clear. Regression-tested.
_CREDENTIAL = re.compile(
    r"""
      \b(?:secret|api[_-]?key|password|passwd|token|authorization)\w*\b
      \s*[:=]\s*
      (?:(?:bearer|basic)\s+)?\S+                   # optional scheme, then the value
    | \b(?:bearer|basic)\s+\S+                      # bare "Bearer <token>"
    """,
    re.IGNORECASE | re.VERBOSE,
)
_QUOTED = re.compile(r"""(['"])(?:\\.|(?!\1).)*\1""")


def redact_error_text(message: str, *, limit: int = MAX_ERROR_CHARS) -> str:
    """Mask credentials and quoted literals, collapse whitespace, cap length."""
    text = _CREDENTIAL.sub("[redacted]", str(message))
    text = _QUOTED.sub("'[redacted]'", text)
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: max(0, limit - len(_TRUNCATED))] + _TRUNCATED
    return text


__all__ = ["MAX_ERROR_CHARS", "redact_error_text"]
