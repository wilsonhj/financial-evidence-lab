# Shared packages

Reusable libraries consumed by `apps/` and `workers/`. Each package is filled
in by the work package that owns it; the scaffold only fixes the layout.

| Package | Owner package | Language |
|---|---|---|
| `contracts/` | `M0-CONTRACTS` (T0003) | OpenAPI / JSON Schema / generated TS client |
| `calculation-engine/` | `M4-MODEL-CALC` (T0403) | Python (decimal calculation engine) |
| `retrieval-evals/` | `M2-CLAIMS-VERIFICATION` (T0214a, T0215) | Python |
| `ui/` | experience packages (M1–M5) | TypeScript / React |

`packages/contracts/` is intentionally absent here: it is created by
`M0-CONTRACTS` so the contract freeze (ADR-0001) owns its first commit.
