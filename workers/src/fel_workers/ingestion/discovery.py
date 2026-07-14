"""SEC filing discovery (T0101, FR-ING-001).

Lists an issuer's filings from the submissions index via any injected
``SecClient`` (the deterministic mock by default; ``LiveSecClient`` when
egress and fair-access compliance are available) and enqueues one
idempotent fetch job per filing on the lease-fenced queue.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import psycopg

from fel_providers.interfaces import SecClient
from fel_workers import queue
from fel_workers.ingestion.sec_client import normalize_cik

JOB_KIND_SEC_DISCOVERY = "sec_discovery"
JOB_KIND_SEC_FILING_FETCH = "sec_filing_fetch"


class DiscoveryError(Exception):
    """The submissions payload does not have the expected shape."""


@dataclass(frozen=True)
class FilingRef:
    """One discovered filing from the submissions index."""

    cik: str
    accession: str
    form: str
    filed_on: date
    primary_document_url: str | None


def _recent_lists(payload: dict[str, object]) -> dict[str, list[object]]:
    filings = payload.get("filings")
    if not isinstance(filings, dict):
        raise DiscoveryError("submissions payload is missing the 'filings' object")
    recent = filings.get("recent")
    if not isinstance(recent, dict):
        raise DiscoveryError("submissions payload is missing 'filings.recent'")
    out: dict[str, list[object]] = {}
    for field in ("accessionNumber", "form", "filingDate", "primaryDocument"):
        value = recent.get(field, [])
        out[field] = list(value) if isinstance(value, list) else []
    return out


def discover_filings(
    client: SecClient,
    cik: str,
    *,
    forms: frozenset[str] | None = None,
) -> list[FilingRef]:
    """List an issuer's filings, optionally filtered to specific form types."""
    normalized = normalize_cik(cik)
    recent = _recent_lists(client.submissions(normalized))
    accessions = recent["accessionNumber"]
    form_list = recent["form"]
    dates = recent["filingDate"]
    documents = recent["primaryDocument"]
    refs: list[FilingRef] = []
    for index, accession in enumerate(accessions):
        form = str(form_list[index]) if index < len(form_list) else ""
        if forms is not None and form not in forms:
            continue
        filed_text = str(dates[index]) if index < len(dates) else ""
        try:
            filed_on = date.fromisoformat(filed_text)
        except ValueError as exc:
            raise DiscoveryError(
                f"filing {accession!r} has unparseable filingDate {filed_text!r}"
            ) from exc
        primary = str(documents[index]) if index < len(documents) and documents[index] else None
        url = None
        if primary:
            accession_nodash = str(accession).replace("-", "")
            url = (
                "https://www.sec.gov/Archives/edgar/data/"
                f"{int(normalized)}/{accession_nodash}/{primary}"
            )
        refs.append(
            FilingRef(
                cik=normalized,
                accession=str(accession),
                form=form,
                filed_on=filed_on,
                primary_document_url=url,
            )
        )
    return refs


def run_discovery_job(
    conn: psycopg.Connection[Any],
    client: SecClient,
    payload: dict[str, object],
    *,
    job_queue: str = "ingestion",
) -> list[FilingRef]:
    """Handle a ``sec_discovery`` job: list filings, enqueue idempotent fetches.

    Fetch jobs are deduplicated per accession via the queue's idempotency
    key, so re-running discovery never duplicates work.
    """
    cik = str(payload.get("cik", ""))
    forms_value = payload.get("forms")
    forms = frozenset(str(f) for f in forms_value) if isinstance(forms_value, list) else None
    refs = discover_filings(client, cik, forms=forms)
    for ref in refs:
        queue.enqueue(
            conn,
            kind=JOB_KIND_SEC_FILING_FETCH,
            payload={
                "cik": ref.cik,
                "accession": ref.accession,
                "form": ref.form,
                "filed_on": ref.filed_on.isoformat(),
                "url": ref.primary_document_url,
            },
            queue=job_queue,
            idempotency_key=f"sec-fetch|{ref.accession}",
        )
    return refs
