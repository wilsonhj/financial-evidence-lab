"""Currency identification only — no FX conversion (M3-NRM-003).

The single implementation of currency handling in the normalizer, called from
``payload.py::_normalize_numeric_fields``. It previously sat here unimported
next to a near-duplicate inline in ``payload.py`` (issue #155), and the two
behaved differently: the orphan *nulled* a malformed currency and inferred one
from the unit, while the live code raised and inferred nothing. The live
semantics are kept — a malformed currency is issuer data that must not be
silently discarded, and a currency the issuer never stated must not be invented
— and only the one rule the live path was missing is added
(``currency_missing_for_monetary``).
"""

from __future__ import annotations

import re
from typing import Any

# ISO-4217 alpha-3, uppercase only. Lowercase is *rejected*, not folded, so the
# ``.upper()`` below is a no-op today. Whether ``"usd"`` should fold to
# ``"USD"`` rather than raise is issue #153's question, and this is now the one
# place that would have to change to answer it.
_ISO_4217 = re.compile(r"^[A-Z]{3}$")

# The contract types ``unit`` as a free-form non-empty string; payloads in this
# repo write the ISO code itself (``"USD"``) where the ontology writes
# ``"USD/yr"``. ``"currency"`` is accepted as the generic monetary unit.
_MONETARY_UNIT = "currency"


def normalize_currency(*, currency: Any, unit: str | None) -> tuple[str | None, list[str]]:
    """Validate a declared currency and report a monetary figure that lacks one.

    Returns ``(currency, blockers)``. ``None`` means the payload declared no
    currency and the caller must leave the field exactly as it found it — an
    absent key stays absent, an explicit ``null`` stays ``null``. Nothing is
    inferred from ``unit``: filling in a currency the issuer did not state is a
    silent repair of a reported financial figure, and the blocker puts the same
    fact in front of a reviewer instead.

    Raises ``ValueError`` for a malformed currency, matching how ``payload.py``
    treats every other structural violation — ``pipeline.normalize_payload``
    turns that into a blocker and carries the payload forward, so nothing is
    dropped.
    """
    blockers: list[str] = []
    if currency is None:
        if _is_monetary_unit(unit):
            # Not redundant with ``validate/definitions.py::_unit_errors``,
            # which reports "currency metric <id> declares no currency" only for
            # a metric the ontology resolves. Guidance and revenue drivers carry
            # free-text metric labels by design, so a "$120 million" guidance
            # point with a null currency cleared every check before this.
            blockers.append("currency_missing_for_monetary")
        return None, blockers
    if not isinstance(currency, str) or not _ISO_4217.fullmatch(currency):
        raise ValueError(f"currency must be ISO-4217 alpha-3 or null: {currency!r}")
    return currency.upper(), blockers


def _is_monetary_unit(unit: str | None) -> bool:
    """True when ``unit`` denominates money and therefore needs a currency.

    Any ISO-4217-shaped unit qualifies rather than a fixed list of codes: the
    version this replaced enumerated six currencies, which would have read a
    CHF, SEK or INR amount as non-monetary and let it through with no currency.

    Only the numerator decides, so the ontology's own per-period spellings
    (``USD/yr``, ``USD/mo``) count: an amount per unit time is still an amount
    of money, and a rate needs a currency for exactly the same reason a level
    does. Checking the bare code alone read every one of them as non-monetary
    — "net new ARR per rep" reported as ``120`` with ``unit: "USD/yr"`` and no
    currency cleared every check, which is the hole this rule exists to close.
    A non-monetary numerator is unaffected: ``count/mo`` stays non-monetary
    because ``count`` is not ISO-shaped.

    Lowercase is deliberately NOT folded here — ``usd`` is rejected upstream
    rather than accepted, and whether it should fold is issue #153's question.
    """
    if not isinstance(unit, str):
        return False
    text = unit.strip()
    if text == _MONETARY_UNIT:
        return True
    numerator = text.split("/", 1)[0]
    return _ISO_4217.fullmatch(numerator) is not None


__all__ = ["normalize_currency"]
