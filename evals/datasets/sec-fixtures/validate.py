"""Validate recovered metadata structure; never certify SEC bytes or feature evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

MANIFEST_SHA256 = "945d36c0c95993b03b54bd4a1af96b7d6c9412a74420cccef39b9687b2d897cc"
COHORT_SHA256 = "3fda084f60f4fd00225d36e0e6233ac03d0f2ff4420cad1b9d2ef95cf72e4b4c"


FIELDS = {
    "id",
    "issuer",
    "form",
    "accession",
    "filed_at",
    "primary_document",
    "url",
    "sha256",
    "why_selected",
    "stress_features",
}
FEATURES = {
    "ixbrl_continuation",
    "ixbrl_dimensional_facts",
    "nested_tables",
    "rotated_tables",
    "unusual_scale_markers",
    "multi_currency",
    "legacy_html_no_ixbrl",
    "amended_filing",
    "restatement_nonreliance",
    "fiscal_year_transition",
    "pre_2018_formatting",
}


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def validate_manifest(data: bytes, cohort_data: bytes) -> list[str]:
    """Return deterministic recovery/structure errors without quoting input contents."""
    errors = []
    for name, content, digest in [
        ("manifest", data, MANIFEST_SHA256),
        ("cohort", cohort_data, COHORT_SHA256),
    ]:
        if hashlib.sha256(content).hexdigest() != digest:
            errors.append(f"{name}.sha256")
    issuers = {}
    try:
        cohort = json.loads(cohort_data.decode("utf-8"), object_pairs_hook=_object)["issuers"]
        if not isinstance(cohort, list) or len(cohort) != 20:
            raise ValueError("cohort shape")
        for issuer in cohort:
            cik, ticker = issuer["cik"], issuer["ticker"]
            if not isinstance(cik, str) or not re.fullmatch(r"[0-9]{10}", cik):
                raise ValueError("cohort cik")
            if not isinstance(ticker, str) or not ticker.strip():
                raise ValueError("cohort ticker")
            issuers[cik] = ticker
        if len(issuers) != 20 or len(set(issuers.values())) != 20:
            raise ValueError("cohort uniqueness")
    except (ValueError, TypeError, KeyError):
        errors.append("cohort.issuers")
    try:
        rows = [
            json.loads(line, object_pairs_hook=_object)
            for line in data.decode("utf-8").splitlines()
        ]
    except ValueError:
        return [*errors, "manifest.jsonl"]
    if len(rows) != 60:
        errors.append("manifest.rows")
    seen: dict[str, set[str]] = {field: set() for field in ("id", "accession", "url", "sha256")}
    represented = set()
    for number, row in enumerate(rows, 1):
        prefix = f"row.{number}."
        if not isinstance(row, dict) or row.keys() != FIELDS:
            errors.append(prefix + "keys")
            continue
        if any(
            not isinstance(row[k], str) or not row[k].strip()
            for k in sorted(FIELDS - {"issuer", "stress_features"})
        ):
            errors.append(prefix + "scalar")
            continue
        for field, values in seen.items():
            if row[field] in values:
                errors.append(f"duplicate.{field}")
            values.add(row[field])
        issuer = row["issuer"]
        issuer_valid = (
            isinstance(issuer, dict)
            and issuer.keys() == {"cik", "ticker"}
            and isinstance(issuer["cik"], str)
            and isinstance(issuer["ticker"], str)
            and bool(re.fullmatch(r"[0-9]{10}", issuer["cik"]))
            and issuers.get(issuer["cik"]) == issuer["ticker"]
        )
        if issuer_valid:
            represented.add(issuer["cik"])
        features = row["stress_features"]
        features_valid = (
            isinstance(features, list)
            and bool(features)
            and all(isinstance(feature, str) and feature in FEATURES for feature in features)
            and len(features) == len(set(features))
        )
        try:
            valid_date = bool(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", row["filed_at"]))
            date.fromisoformat(row["filed_at"])
        except ValueError:
            valid_date = False
        checks = {
            "id": row["id"] == f"FX-{number:04d}",
            "issuer": issuer_valid,
            "accession": bool(re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", row["accession"])),
            "filed_at": valid_date,
            "sha256": bool(re.fullmatch(r"[0-9a-f]{64}", row["sha256"])),
            "form": row["form"] in {"10-K", "10-Q", "10-K/A", "10-Q/A"},
            "primary_document": bool(
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", row["primary_document"])
            ),
            "stress_features": features_valid
            and (("amended_filing" in features) == row["form"].endswith("/A"))
            and (("pre_2018_formatting" in features) == (row["filed_at"] < "2018-01-01")),
        }
        if issuer_valid:
            expected = (
                f"https://www.sec.gov/Archives/edgar/data/{int(issuer['cik'])}/"
                f"{row['accession'].replace('-', '')}/{row['primary_document']}"
            )
            checks["url"] = row["url"] == expected
        errors.extend(prefix + field for field, valid in checks.items() if not valid)
    if represented != set(issuers):
        errors.append("manifest.issuers")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--structural-only", action="store_true")
    args = parser.parse_args(argv)
    report: dict[str, Any] = {
        "scope": "historical_structure",
        "acceptance_passed": False,
        "verified_feature_count": 0,
        "historical_feature_assertions": {},
        "unavailable_evidence": [
            "fetched_bytes",
            "receipts",
            "feature_witnesses",
            "representative_excerpts",
            "amendment_original_provenance",
        ],
    }
    root = Path(__file__).resolve().parent
    try:
        data = (root / "manifest.jsonl").read_bytes()
        cohort = (root.parent / "issuer-cohort.json").read_bytes()
        errors = validate_manifest(data, cohort)
    except OSError:
        errors = ["input.read"]
    report.update(errors=errors, structural_valid=not errors)
    if not errors:
        rows = [json.loads(line) for line in data.splitlines()]
        report["historical_feature_assertions"] = Counter(
            feature for row in rows for feature in row["stress_features"]
        )
    print(json.dumps(report, sort_keys=True))
    return 1 if errors else (0 if args.structural_only else 2)


if __name__ == "__main__":
    raise SystemExit(main())
