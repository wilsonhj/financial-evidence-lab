# `@fel/calculation-engine` (`fel_calculation_engine`)

Server-side Decimal calculation engine for the Revenue Model Composer
(spec §8.5, FR-MOD-001 / FR-MOD-002). Authoritative math is Decimal-only,
typed-unit, and deterministic. Language models must not execute it.

## What it does

- Nine node kinds (source fact, assumption, driver, formula, aggregation,
  scenario override, forecast output, validation check, reported output)
- Fail-closed cycle detection and versioned, content-addressed snapshots
- Decimal arithmetic under `CALC_CONTEXT` (34 digits, banker's rounding)
- Closed unit algebra, typed fiscal periods, percent → ratio normalization
- Provenance retained through recalculation; derived cutoffs are `max(parents)`
- Property tests and a deterministic 5,000-node p95 recalculation gate

## Leaf values

Construct Decimals from strings (`Decimal("0.1")`). `Decimal(0.1)` — the
IEEE-754 binary expansion — is rejected at `require_decimal`.

## Tests

```bash
pytest packages/calculation-engine/tests
```
