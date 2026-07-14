"""Deterministic synthetic ``SecClient`` for the corpus-QA harness (T0112).

Serves a fabricated submissions index and fabricated filing bytes for every
issuer in the benchmark cohort, generated from committed templates under
``evals/datasets/synthetic-corpus/``. Every value is derived
deterministically from the issuer CIK + accession (same inputs -> same
bytes, no randomness, no network), and every generated document carries a
SYNTHETIC banner. The CIK is used ONLY to key the cohort slot; no content
resembles or is derived from any real filing.

The synthetic plan deliberately includes corpus-quality events so the
harness metrics exercise the real quarantine and linkage paths:

- every issuer: one clean 10-K (FY) and one clean 10-Q (Q1), each with a
  duplicated revenue presentation (duplicate detection);
- every 5th issuer: a 10-Q/A amending the Q1 revenue (restatement linkage);
- issuers at index % 7 == 3: a corrupt filing with an undefined XBRL
  context (quarantine reason UNKNOWN_CONTEXT);
- issuers at index % 7 == 5: a corrupt filing with an unregistered iXBRL
  transformation format (quarantine reason UNKNOWN_FORMAT).
"""

from __future__ import annotations

import hashlib
import pathlib
from dataclasses import dataclass

TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent.parent / "datasets" / "synthetic-corpus"

_CLEAN_TEMPLATE = "filing_template.html"
_CORRUPT_CONTEXT_TEMPLATE = "corrupt_missing_context_template.html"
_CORRUPT_FORMAT_TEMPLATE = "corrupt_unknown_format_template.html"

_BASE_URL = "https://synthetic.invalid/corpus-qa"


@dataclass(frozen=True)
class SyntheticFiling:
    """One fabricated filing in an issuer's synthetic submissions index."""

    cik: str
    accession: str
    form: str
    filed_on: str
    primary_document: str
    template: str
    period_start: str
    period_end: str
    instant: str
    revenue_offset: int
    value_seed: str
    """Seed for the fabricated values. An amendment reuses the amended
    filing's seed so ONLY the deliberately-offset revenue differs — the
    restatement linkage stays surgical instead of restating every fact."""


def _digits(seed: str, modulus: int, floor: int) -> int:
    """Deterministic pseudo-value in [floor, floor + modulus)."""
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return floor + int(digest[:12], 16) % modulus


def _comma(value: int) -> str:
    return f"{value:,}"


def build_plan(cik: str, index: int) -> list[SyntheticFiling]:
    """The deterministic synthetic filing plan for one cohort slot."""

    def filing(
        sequence: int,
        form: str,
        filed_on: str,
        template: str,
        period_start: str,
        period_end: str,
        instant: str,
        revenue_offset: int = 0,
        value_seed: str | None = None,
    ) -> SyntheticFiling:
        accession = f"{cik}-26-{sequence:06d}"
        return SyntheticFiling(
            cik=cik,
            accession=accession,
            form=form,
            filed_on=filed_on,
            primary_document=f"syn-{accession}.htm",
            template=template,
            period_start=period_start,
            period_end=period_end,
            instant=instant,
            revenue_offset=revenue_offset,
            value_seed=value_seed if value_seed is not None else accession,
        )

    plan = [
        filing(1, "10-K", "2026-02-10", _CLEAN_TEMPLATE, "2025-01-01", "2025-12-31", "2025-12-31"),
        filing(2, "10-Q", "2026-05-08", _CLEAN_TEMPLATE, "2026-01-01", "2026-03-31", "2026-03-31"),
    ]
    if index % 7 == 3:
        plan.append(
            filing(
                3,
                "8-K",
                "2026-06-01",
                _CORRUPT_CONTEXT_TEMPLATE,
                "2026-04-01",
                "2026-06-01",
                "2026-06-01",
            )
        )
    if index % 7 == 5:
        plan.append(
            filing(
                4,
                "8-K",
                "2026-06-20",
                _CORRUPT_FORMAT_TEMPLATE,
                "2026-04-01",
                "2026-06-20",
                "2026-06-20",
            )
        )
    if index % 5 == 0:
        # An amendment restating Q1 revenue: same period and SAME value
        # seed as filing 2 (so every other fact repeats identically),
        # different accession, revenue offset by a fixed delta.
        plan.append(
            filing(
                5,
                "10-Q/A",
                "2026-06-15",
                _CLEAN_TEMPLATE,
                "2026-01-01",
                "2026-03-31",
                "2026-03-31",
                revenue_offset=37,
                value_seed=plan[1].accession,
            )
        )
    return plan


def render_filing(filing: SyntheticFiling) -> bytes:
    """Deterministically render one synthetic filing's bytes."""
    template = (TEMPLATES_DIR / filing.template).read_text()
    seed = f"{filing.cik}|{filing.value_seed}"
    revenue = _digits(seed + "|revenue", 9000, 1000) + filing.revenue_offset
    values = {
        "__ISSUER_LABEL__": f"Synthetic Cohort Issuer CIK {filing.cik}",
        "__CIK__": filing.cik,
        "__ACCESSION__": filing.accession,
        "__FORM__": filing.form,
        "__PERIOD_START__": filing.period_start,
        "__PERIOD_END__": filing.period_end,
        "__INSTANT__": filing.instant,
        "__REVENUE__": _comma(revenue),
        "__CHARGE__": _comma(_digits(seed + "|charge", 900, 100)),
        "__SEGMENT_REVENUE__": _comma(_digits(seed + "|segment", 800, 100)),
        "__ASSETS__": _comma(_digits(seed + "|assets", 90000, 10000)),
        "__SHARES__": _comma(_digits(seed + "|shares", 400000, 50000)),
    }
    rendered = template
    for token, value in values.items():
        rendered = rendered.replace(token, value)
    return rendered.encode()


class SyntheticCohortSecClient:
    """``SecClient``-shaped mock over the committed synthetic templates.

    ``submissions`` returns a fabricated EDGAR-shaped index for the CIK's
    cohort slot; ``fetch_document`` returns the deterministic synthetic
    bytes for the URL discovery derived from that index. Nothing is ever
    fetched from the network.
    """

    def __init__(self, ciks: list[str]) -> None:
        self._plans: dict[str, list[SyntheticFiling]] = {
            cik: build_plan(cik, index) for index, cik in enumerate(ciks)
        }
        self._by_document: dict[str, SyntheticFiling] = {}
        for plan in self._plans.values():
            for filing in plan:
                self._by_document[filing.primary_document] = filing

    def submissions(self, cik: str) -> dict[str, object]:
        plan = self._plans.get(cik)
        if plan is None:
            raise KeyError(f"CIK {cik!r} is not in the synthetic cohort plan")
        return {
            "_note": (
                "SYNTHETIC submissions index generated by the corpus-QA "
                "harness; every filing is fabricated."
            ),
            "cik": cik,
            "filings": {
                "recent": {
                    "accessionNumber": [filing.accession for filing in plan],
                    "form": [filing.form for filing in plan],
                    "filingDate": [filing.filed_on for filing in plan],
                    "primaryDocument": [filing.primary_document for filing in plan],
                }
            },
        }

    def fetch_document(self, url: str) -> bytes:
        name = url.rsplit("/", 1)[-1]
        filing = self._by_document.get(name)
        if filing is None:
            raise KeyError(f"URL {url!r} does not name a planned synthetic document")
        return render_filing(filing)


def base_url() -> str:
    """Base URL marker for synthetic documents (never fetched)."""
    return _BASE_URL
