"""Check an installed production environment without pytest's source paths."""

from __future__ import annotations

import importlib
import json
from importlib.metadata import distributions


def main() -> None:
    installed = {
        str(dist.metadata["Name"]).lower().replace("_", "-"): dist.version
        for dist in distributions()
    }
    development_tools = {"mypy", "bandit", "pytest", "pytest-cov", "black", "ruff", "pip-audit"}
    unexpected = sorted(development_tools & installed.keys())
    if unexpected:
        raise RuntimeError(f"development tools in production environment: {unexpected}")
    for module in ("app.main", "fel_workers.__main__", "fel_workers.extraction.handler"):
        importlib.import_module(module)
    print(json.dumps(installed, sort_keys=True))


if __name__ == "__main__":
    main()
