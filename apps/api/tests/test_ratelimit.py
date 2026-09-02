"""#191: per-organization token-bucket rate limiting.

The bucket unit tests run without a database (injected clock, no sleeping).
The HTTP test needs one, because the limiter deliberately sits behind
authentication and membership resolution.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth import make_mock_token
from app.ratelimit import RateLimiter, set_limiter
from tests.conftest import requires_db


class _Clock:
    """A hand-advanced monotonic clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def clock() -> _Clock:
    return _Clock()


@pytest.fixture(autouse=True)
def _restore_limiter() -> Iterator[None]:
    """Never leak a test's limiter into another test (or another module).

    The limiter is process-wide, so a fake-clock limiter left installed would
    silently throttle every later suite.
    """
    set_limiter(None)
    yield
    set_limiter(None)


def test_burst_is_spent_then_refills_at_the_configured_rate(clock: _Clock) -> None:
    limiter = RateLimiter(qps=2.0, burst=3, clock=clock)

    # The full burst is available immediately.
    assert [limiter.check("org", "route") for _ in range(3)] == [None, None, None]

    # The fourth request in the same instant is refused, with a whole-second
    # Retry-After a client can actually act on.
    retry_after = limiter.check("org", "route")
    assert retry_after is not None and retry_after >= 1

    # Refill is time-based, not request-based: half a second buys one token.
    clock.advance(0.5)
    assert limiter.check("org", "route") is None
    assert limiter.check("org", "route") is not None

    # The bucket never accumulates beyond the burst ceiling.
    clock.advance(3600)
    assert [limiter.check("org", "route") for _ in range(3)] == [None, None, None]
    assert limiter.check("org", "route") is not None


def test_buckets_are_isolated_per_org_and_per_route(clock: _Clock) -> None:
    limiter = RateLimiter(qps=1.0, burst=1, clock=clock)
    assert limiter.check("org-a", "createQuery") is None
    # Same org, exhausted route.
    assert limiter.check("org-a", "createQuery") is not None
    # A different route for that org is untouched...
    assert limiter.check("org-a", "createQueryRerun") is None
    # ...and so is a different tenant. One noisy org cannot spend another's
    # budget, which is the whole point of keying by org.
    assert limiter.check("org-b", "createQuery") is None


def test_zero_qps_disables_the_limiter(clock: _Clock) -> None:
    limiter = RateLimiter(qps=0.0, burst=0, clock=clock)
    assert not limiter.enabled
    assert all(limiter.check("org", "route") is None for _ in range(100))


def test_negative_configuration_is_rejected() -> None:
    with pytest.raises(ValueError):
        RateLimiter(qps=-1.0, burst=5)
    with pytest.raises(ValueError):
        RateLimiter(qps=1.0, burst=-5)


@requires_db
def test_http_429_carries_retry_after_and_the_error_envelope(
    client: TestClient, org_fixture: tuple[str, str], db_url: str, clock: _Clock
) -> None:
    """The second call in one instant is refused before the endpoint runs."""
    set_limiter(RateLimiter(qps=1.0, burst=1, clock=clock))
    org_id, user_id = org_fixture
    headers = {
        "Authorization": f"Bearer {make_mock_token(org_id, user_id, 'owner')}",
        "Idempotency-Key": f"fb-{uuid.uuid4()}",
    }
    body = {"item_id": str(uuid.uuid4()), "label": "relevant"}
    url = f"/v1/retrieval-runs/{uuid.uuid4()}/feedback"

    # The first call is admitted and reaches the endpoint (the run does not
    # exist, so it 404s — what matters is that the limiter let it through).
    first = client.post(url, headers=headers, json=body)
    assert first.status_code == 404, first.text

    second = client.post(url, headers=headers, json=body)
    assert second.status_code == 429, second.text
    assert second.headers["Retry-After"] == "1"
    error = second.json()["error"]
    assert error["code"] == "RATE_LIMITED"
    assert error["details"]["route"] == "createRetrievalFeedback"
    assert error["request_id"]

    # Once the bucket refills, the same request is admitted again.
    clock.advance(1.0)
    assert client.post(url, headers=headers, json=body).status_code == 404
