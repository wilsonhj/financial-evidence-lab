# Shared packages

Reusable first-party libraries consumed by `apps/api`, `apps/web`, `workers`, and `evals`.

| Package | Directory | Language | Responsibility |
| :--- | :--- | :--- | :--- |
| `@fel/contracts` | [`contracts/`](./contracts/README.md) | OpenAPI 3.1 / JSON Schema / TypeScript | Frozen API and domain contracts (v0.6.0), AJV runtime validators, and generated TypeScript types consumed by `apps/web` and verified against `apps/api`. |
| `fel_calculation_engine` | [`calculation-engine/`](./calculation-engine/README.md) | Python 3.11 | Deterministic 34-digit IEEE Decimal calculation DAG, 9 frozen node kinds, closed unit algebra, `fel-formula/v1` expression ASTs, exact-SCC Jacobi fixed-point iteration, Base/Bull/Bear scenario overrides, and 5,000-node recalculation benchmark. |
| `fel_ontology` | [`ontology/`](./ontology/) | Python 3.11 | First-party SaaS metric ontology (`saas-metrics/v1`: 9 families, 14 canonical KPIs), enum/qualifier validation, content-hash pinning, and deterministic comparability keys. |
| `fel_providers` | [`providers/`](./providers/) | Python 3.11 | Stable external-provider protocols and deterministic mocks for SEC EDGAR, FRED, market data, storage, OpenAI 512-dim embeddings (`openai_embeddings.py`), OpenAI structured outputs (`openai_structured.py`), and offline BYOK credential encryption (`credential_cipher.py`). |
| `fel_retrieval` | [`retrieval/`](./retrieval/README.md) | Python 3.11 | Deterministic section/span chunking, cutoff-safe 4-lane retrieval (dense, lexical, fact, table), query planner, Reciprocal Rank Fusion (`k=60`), atomic claim decomposition, citation entailment verification, and byte-stable trace replay. |
| `fel_retrieval_evals` | [`retrieval-evals/`](./retrieval-evals/) | Python 3.11 | Retrieval benchmark dataset compiler, exact-vs-HNSW vector oracle, and Recall/MRR/nDCG/temporal-validity evaluation metrics. |
