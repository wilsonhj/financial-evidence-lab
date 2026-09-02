#!/usr/bin/env python3
"""Match changed files against `docs/handoff/workstreams.yaml`'s `shared_paths`.

Used by `.github/workflows/shared-paths.yml` to fail a PR that touches a
shared path without the `contract-change` label. Per the ruling recorded in
`docs/handoff/STATUS.md` under #141, this check is label-only: it does not
attempt to verify an ADR exists (that review is done by a human).

Depends only on the standard library plus PyYAML (already a
`requirements-dev.txt` dependency, used elsewhere for OpenAPI parity tests).

Exit codes
----------
0   no offending files, or the PR carries the label
1   a shared path changed and the PR does not carry the label
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

DEFAULT_WORKSTREAMS_PATH = Path("docs/handoff/workstreams.yaml")


def load_shared_paths(workstreams_path: Path = DEFAULT_WORKSTREAMS_PATH) -> list[str]:
    """Read the `shared_paths` list out of `workstreams.yaml`.

    Raises `ValueError` if the key is missing or not a list of strings, so a
    malformed ledger fails loudly instead of silently matching nothing.
    """
    data = yaml.safe_load(workstreams_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "shared_paths" not in data:
        raise ValueError(f"{workstreams_path}: no top-level 'shared_paths' key")
    patterns = data["shared_paths"]
    if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
        raise ValueError(f"{workstreams_path}: 'shared_paths' must be a list of strings")
    return patterns


def _pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a gitignore-style glob (with `**`) to a compiled regex.

    Supported tokens:
    - `**/` matches zero or more path segments (including none).
    - `**` (not followed by `/`) matches anything, including `/`.
    - `*` matches anything except `/`.
    - `?` matches a single character except `/`.
    - Everything else is matched literally.
    """
    i, n = 0, len(pattern)
    out: list[str] = []
    while i < n:
        c = pattern[i]
        if c == "*" and i + 1 < n and pattern[i + 1] == "*":
            if i + 2 < n and pattern[i + 2] == "/":
                out.append("(?:.*/)?")
                i += 3
            else:
                out.append(".*")
                i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def match_shared_paths(changed_files: list[str], patterns: list[str]) -> list[str]:
    """Return the subset of `changed_files` that match any of `patterns`."""
    regexes = [_pattern_to_regex(p) for p in patterns]
    offenders = []
    for path in changed_files:
        normalized = path.strip().replace("\\", "/")
        if not normalized:
            continue
        if any(rx.match(normalized) for rx in regexes):
            offenders.append(normalized)
    return offenders


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workstreams",
        type=Path,
        default=DEFAULT_WORKSTREAMS_PATH,
        help="path to workstreams.yaml (default: %(default)s)",
    )
    parser.add_argument(
        "--has-label",
        action="store_true",
        help="set when the pull request already carries the contract-change label",
    )
    args = parser.parse_args(argv)

    changed_files = [line for line in sys.stdin.read().splitlines() if line.strip()]
    patterns = load_shared_paths(args.workstreams)
    offenders = match_shared_paths(changed_files, patterns)

    if not offenders:
        print("shared-paths: no shared paths touched.")
        return 0

    if args.has_label:
        print("shared-paths: shared paths touched, but the 'contract-change' " "label is present:")
        for f in offenders:
            print(f"  - {f}")
        return 0

    print(
        "shared-paths: this PR touches shared_paths (docs/handoff/workstreams.yaml) "
        "without the 'contract-change' label:",
        file=sys.stderr,
    )
    for f in offenders:
        print(f"  - {f}", file=sys.stderr)
    print(
        "\nAdd the 'contract-change' label (see AGENTS.md 'Shared paths' and "
        "docs/handoff/STATUS.md #141) before merging.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
