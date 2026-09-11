# Historical SEC fixture manifest — unverified recovery

This directory recovers 60 historical fixture records for the canonical
[20-issuer cohort](../issuer-cohort.json). The records support inspection and
future parser-fixture verification; they are **not a verified golden baseline**.
Issue #81 remains open. No SEC requests were made during this recovery.

## Source and integrity

The manifest is copied byte-for-byte from final historical commit
`d8fd80ea3ed0f09d981b5a072e18a099f3aedd51`, rather than merging its obsolete
integration branch. That final revision removed 15 disputed multi-currency tags.

| Material | Fingerprint |
| --- | --- |
| Manifest Git blob | `5a2662157357460f76c556507f50d5eb7b5132cb` |
| Manifest bytes | 33,123 |
| Manifest SHA-256 | `945d36c0c95993b03b54bd4a1af96b7d6c9412a74420cccef39b9687b2d897cc` |
| Read-only cohort SHA-256 | `3fda084f60f4fd00225d36e0e6233ac03d0f2ff4420cad1b9d2ef95cf72e4b4c` |
| Source MIT license SHA-256 | `9df2530031b509fd7af008447f39b631abb2058c31cfe2febb49a3de3cea83a9` |

These fingerprints establish recovery from Git, not correctness of the hashes
stored for filing bytes. Full filings, fetch receipts, feature witnesses,
amendment-original provenance and representative excerpt bytes were not recovered.
Historical author claims about fetched bytes, complete histories and absent
features have not been reverified.

## Recorded assertions

There are 60 distinct IDs/accessions/URLs/hash strings covering all 20 cohort
CIK/ticker pairs. Stored forms comprise 20 10-K, 30 10-Q, six 10-K/A and four
10-Q/A. The seven distinct **historical feature assertions** are:

| Label | Records |
| --- | ---: |
| unusual_scale_markers | 52 |
| ixbrl_continuation | 45 |
| ixbrl_dimensional_facts | 43 |
| legacy_html_no_ixbrl | 14 |
| pre_2018_formatting | 14 |
| amended_filing | 10 |
| multi_currency | 2 |

None of these feature types is freshly verified. The required full-acceptance
gate remains at least eight verified feature types. Stored dates, forms and
selection explanations are historical metadata, not independently proven SEC facts.

## Offline checks

From the repository root, using its locked Python 3.11 environment:

```bash
python -m unittest discover -s evals/datasets/sec-fixtures/tests -p 'test_*.py' -v
python evals/datasets/sec-fixtures/validate.py --structural-only
python evals/datasets/sec-fixtures/validate.py
```

The explicit structural command exits 0 only for intact, internally consistent
recovery data. It checks fingerprints, strict JSONL types, dates, identities,
cohort membership, archive URL consistency and recognized labels. Filing-agent
accession prefixes may differ from issuer CIKs. It performs no network access or
feature detection. Its report always has `acceptance_passed=false` and
`verified_feature_count=0`. Invalid recovery data exits 1.

The default command intentionally exits **2**: full acceptance is unavailable.
It cannot certify filing bytes, feature tags, amendment originals or the eight-feature
gate. Nearby cache files cannot change that. The tests here are outside root
pytest discovery; run the explicit unittest command on the reviewed head.

## Sanitization, licensing and remaining work

The historical README contained a personal SEC contact identity. This recovery
omits that identity and documents only the existing `FEL_SEC_USER_AGENT` setting
name. No contact was adopted and no SEC requests were made. Both README files
were rewritten; the historical README blobs were
`07f2eab0901902e1a77a54bd0713911dfee842dd` and
`09117b27ba02fba2e83480fd2441c0ba50ca24b1` respectively.

[SOURCE-LICENSE.txt](SOURCE-LICENSE.txt) preserves the source commit's complete
MIT notice and original copyright. Current root license files remain unchanged.
This source notice does not establish licensing rights for issuer filing contents.

A later authorized phase must verify actual filing bytes and receipts, feature
witnesses, representative excerpts, the ten amendment-original relationships,
and three to six supplemental non-cohort issuers. SEC access still requires an
approved current `FEL_SEC_USER_AGENT` and bounded request authorization. This
offline restoration neither satisfies nor bypasses those prerequisites.
