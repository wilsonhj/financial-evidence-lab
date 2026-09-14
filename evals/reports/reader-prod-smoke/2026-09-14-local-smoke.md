# Local reader verification — 2026-09-14

This is local preparation for #108, **not hosted acceptance**. Verified source
checkpoint `c399a22` includes worker `9a5732d` and ingestion harness `3e508e3`.
Controller atomic command publication, graceful shutdown and sanitized native HTTP probes were verified in the final rerun.

Six production-build Chromium tests passed in 17.3 seconds against real
Uvicorn, PostgreSQL 17/pgvector and local canonical storage. Four committed
synthetic filings were consumed by the actual worker in strict fixture mode;
all jobs and ingestion runs succeeded. No SQL evidence rows were seeded.

- Exact selected non-first-section quote: `The exact verified evidence for amendment2 is in this non-first section.`
- Span hash: `sha256:97032b54d1e4615768d2a7f04724d8e60979e6d029bee0559b834e5593cf16d7`.
- Both amendments link to a terminal authority after complete history loads.
- Current and historical corpus membership, explicit version and repeatability pass.
- Future and absent document IDs return equal 404 envelopes apart from request IDs.
- Missing/invalid credentials return 401; denied membership returns403. Separate
  real Next services display Sign in required / Access denied, without false404.
- A real canonical byte mutation returns INTEGRITY_ERROR and a browser alert with
  no verified quote. Restoration succeeds and subsequent read returns200.
- Stopping the owned API child produces a real local connection failure and an
  unavailable browser state. Restart restores citation rendering. This is **not**
  evidence of Railway502/503; no platform-generated status is claimed.

[Verified citation](2026-09-14-local-valid-non-first-section.png) ·
[Corrupt canonical blob](2026-09-14-local-invalid-canonical-blob.png)

Six browser-only traces were saved locally and scanned, including ZIP entries, for mock bearer values; no credential-bearing artifacts were found. Raw browser results/logs are retained at
`/private/tmp/fel-reader108-browser-final2.log` and the worktree's
`apps/web/test-results`. Authenticated HTTP probe traffic is excluded
from the browser trace; no HAR containing API credentials is published.

Remaining: dedicated Railway target/access, protected-environment hosted run,
actual edge5xx observation and recovery, deployed revision/URL artifact record.
Competing derived versions of a single accession remain unexercised: current
production parser/normalizer constants yield one version, repeat jobs are
no-ops, and modified source bytes quarantine. No fake version override was used.

Screenshot SHA256:

- `2026-09-14-local-invalid-canonical-blob.png`: `042fc459b63f842f34d69f062a67916fc5ecc19aa23bc21ebea137e1a995bdf1`

- `2026-09-14-local-valid-non-first-section.png`: `cd35c0a65e73a70eb7b2c24f9cf183602cce5fc7982b3692e623d2e5c66e6099`
