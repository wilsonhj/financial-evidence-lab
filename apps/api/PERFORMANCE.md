# API performance checks

The default retrieval API suite checks a load-independent SQL-operation budget.
It does not use wall-clock latency as a functional correctness signal.

The create-query p95 check is opt-in because it is meaningful only on a quiet,
controlled host. Run it against a disposable migrated PostgreSQL database and
describe the machine and database in `FEL_QUERY_BENCHMARK_PROFILE`. Set the
target explicitly from the benchmark protocol being exercised:

```sh
FEL_RUN_QUERY_BENCHMARK=1 \
FEL_QUERY_BENCHMARK_PROFILE='8 vCPU/32 GB API; 8 vCPU/32 GB PostgreSQL; local network' \
FEL_QUERY_BENCHMARK_P95_SECONDS=2.0 \
TEST_DATABASE_URL=postgresql://localhost/fel_test \
pytest apps/api/tests/test_retrieval_api.py::test_create_query_p95_benchmark -q -s
```

This seeded, single-client mock-provider measurement is diagnostic evidence. It
does not satisfy `T0215`, whose reference profile requires 25 concurrent users
and the reference corpus defined in the parent specification.
