"""Error text reaching durable columns must not carry secrets or filing content."""

from __future__ import annotations

import pytest

from fel_workers.redact import MAX_ERROR_CHARS, redact_error_text


@pytest.mark.parametrize(
    ("message", "secret"),
    [
        # The regression this module exists for: a keyed credential whose value
        # is preceded by a scheme word. A bare `\S+` value consumes only
        # "Bearer" and leaves the token in the clear.
        ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
        ("authorization: Bearer sk-live-SECRET", "sk-live-SECRET"),
        ("Authorization=Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("Bearer sk-live-SECRET", "sk-live-SECRET"),
        ("api_key=SECRET123", "SECRET123"),
        ("API-Key: SECRET123", "SECRET123"),
        ("password: hunter2", "hunter2"),
        ("token=abc123", "abc123"),
    ],
)
def test_credentials_never_survive(message: str, secret: str) -> None:
    assert secret not in redact_error_text(message)


@pytest.mark.parametrize(
    ("message", "content"),
    [
        # Normalizer/validator errors interpolate the offending value with
        # {value!r}, so the quoted run is a slice of a filing. No keyword rule
        # catches that -- only a positional one.
        ("cannot normalize raw_value 'ACME reported ARR of $4.2M'", "ACME reported"),
        ('bad value "confidential filing text"', "confidential filing"),
    ],
)
def test_quoted_document_content_never_survives(message: str, content: str) -> None:
    assert content not in redact_error_text(message)


def test_ordinary_diagnostics_stay_readable() -> None:
    """Redaction must not destroy the operational value of the message."""
    msg = "stage classify failed: provider timeout after 30s"
    assert redact_error_text(msg) == msg


def test_length_is_capped() -> None:
    assert len(redact_error_text("x" * 5000)) <= MAX_ERROR_CHARS


def test_whitespace_is_collapsed() -> None:
    assert redact_error_text("a\n\n  b\tc") == "a b c"
