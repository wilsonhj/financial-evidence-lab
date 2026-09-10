# Reproducible Python runtime

`bash scripts/runtime/lock.sh` compiles the human-edited requirements and
first-party package metadata into hash-verified runtime and development locks.
The development lock is constrained to the runtime versions. Build tools have
their own lock and run only in a temporary wheel-builder environment.

Both Railway services run `bash scripts/runtime/install.sh`. It installs the
locked third-party closure, builds first-party wheels from this checkout without
dependency resolution, and checks installed API/worker imports with Python's
isolated mode. Developer tools are rejected. The API needs the provider,
retrieval and worker packages even though pytest can import their source trees.

To check a clean environment locally:

```sh
python3.11 -m venv /tmp/fel-runtime-check
bash scripts/runtime/install.sh /tmp/fel-runtime-check/bin/python
```

CI builds two clean environments and compares their installed name/version
manifests. It also audits the runtime, development and build locks. This proves
dependency version reproducibility and installed imports, not byte-identical
wheels or a hosted deployment. Regenerate locks when package metadata changes;
review dependency upgrades and run the full CI suite before merging them.

Railway checks `/health` during deployment startup, not continuously. The
worker therefore also exits with status 1 when its queue liveness becomes
stale, allowing the configured `ON_FAILURE` policy to restart it. Successful
lease heartbeats keep legitimate long-running jobs healthy; failed heartbeats
do not. Local subprocess tests prove the exit and supervisor contract. Hosted
restart acceptance remains pending a configured Railway environment. See the
[Railway healthcheck contract](https://docs.railway.com/deployments/healthchecks).
