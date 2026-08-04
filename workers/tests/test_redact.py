"""Error text reaching durable columns must not carry secrets or filing content."""

from __future__ import annotations

import pytest

from fel_workers.redact import MAX_ERROR_CHARS, redact_error_text, redact_job_error_text


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


@pytest.mark.parametrize(
    ("message", "secret"),
    [
        ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
        ("{'api_key': 'sk-live-SECRET', 'ticker': 'CRM'}", "sk-live-SECRET"),
        ('{"token": "SECRET123", "accession": "0001-25-000001"}', "SECRET123"),
        ("password=hunter2", "hunter2"),
        ("FEL_OPENAI_API_KEY=sk-live-abcdef", "sk-live-abcdef"),
        ("access_token=top-secret", "top-secret"),
        ("client_secret=top-secret", "top-secret"),
        ("{'api_key': b'sk-bytes-secret'}", "sk-bytes-secret"),
        ('api_key="secret with spaces"', "secret with spaces"),
        ("api_key='abc def'", "abc def"),
        ("{'api_key': \"abc'def\"}", "abc'def"),
        ('{"api_key": "abc\\"def"}', 'abc\\"def'),
    ],
)
def test_job_error_credentials_never_survive(message: str, secret: str) -> None:
    assert secret not in redact_job_error_text(message)


def test_job_error_keeps_quoted_operational_identifiers() -> None:
    message = "unknown job kind 'sec_filing_fetch' for ticker 'CRM' accession '0001-25-000001'"

    assert redact_job_error_text(message) == message


def test_job_error_is_collapsed_and_capped() -> None:
    cleaned = redact_job_error_text("ticker 'CRM'\n\n" + "x" * 5000)

    assert "\n" not in cleaned
    assert "ticker 'CRM'" in cleaned
    assert len(cleaned) <= MAX_ERROR_CHARS
