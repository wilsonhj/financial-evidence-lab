#!/usr/bin/env python3
"""Claude Code PreToolUse hook: keep agent edits inside the work package's lane.

Enforces two rules from AGENTS.md at edit time, before the agent spends a cycle:

1. Shared paths (AGENTS.md "Shared paths") need the `contract-change` label and
   integration-lead review, so an edit to one asks first. This list mirrors
   `.github/workflows/shared-paths.yml`; a test fails if the two drift.
2. A branch listed in `docs/handoff/workstreams.yaml` may only edit that
   package's `allowed_paths`. Nothing in CI checks this today.

The hook never decides on its own authority: it answers `ask` (or `deny` when
FEL_PATH_GUARD=deny, for unattended runs) because both rules have legitimate
exceptions. It is fail-open: any error, unknown branch, or unreadable registry
exits 0 with no output, so a hook bug cannot stall a session. CI remains the
backstop. Only Edit, Write, MultiEdit and NotebookEdit are inspected; shell
commands that write files (sed -i, redirects, tee) are not.

FEL_PATH_GUARD: "ask" (default) | "deny" | "off".
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

SHARED_PREFIXES: tuple[str, ...] = (
    ".github/",
    ".specify/",
    "specs/",
    "packages/contracts/",
    "db/migrations/",
    "docs/decisions/",
)
SHARED_EXACT: frozenset[str] = frozenset(
    {
        "docs/handoff/workstreams.yaml",
        "docs/handoff/STATUS.md",
        "AGENTS.md",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "pyproject.toml",
        "Makefile",
    }
)
WORKSTREAMS = "docs/handoff/workstreams.yaml"
PATH_ARGUMENT = {
    "Edit": "file_path",
    "Write": "file_path",
    "MultiEdit": "file_path",
    "NotebookEdit": "notebook_path",
}


def is_shared(rel: str) -> bool:
    return rel in SHARED_EXACT or rel.startswith(SHARED_PREFIXES)


def parse_packages(text: str) -> list[dict[str, Any]]:
    """Read id, branch, status and allowed_paths from workstreams.yaml.

    A line parser, not a YAML library, so the hook runs under any python3. The
    file's shape is regular; a test compares this against PyYAML on the real file.
    """
    packages: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    in_paths = False
    for raw in text.splitlines():
        line = re.sub(r"\s+#.*$", "", raw).rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        head = re.match(r"^  - id:\s*(\S+)", line)
        if head:
            cur = {"id": head[1], "branch": "", "status": "", "allowed_paths": []}
            packages.append(cur)
            in_paths = False
            continue
        if cur is None:
            continue
        scalar = re.match(r"^    (branch|status):\s*(\S+)", line)
        if scalar:
            cur[scalar[1]] = scalar[2]
            in_paths = False
            continue
        paths = re.match(r"^    allowed_paths:\s*(.*)$", line)
        if paths:
            rest = paths[1].strip()
            if rest.startswith("["):
                items = rest.strip("[]").split(",")
                cur["allowed_paths"] = [i.strip().strip("'\"") for i in items if i.strip()]
                in_paths = False
            else:
                in_paths = True
            continue
        if in_paths:
            entry = re.match(r"^      - (.+)$", line)
            if entry:
                cur["allowed_paths"].append(entry[1].strip().strip("'\""))
                continue
            in_paths = False
    return packages


def _glob(pattern: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def in_scope(rel: str, patterns: list[str]) -> bool:
    return any(_glob(p).match(rel) for p in patterns)


def owners_of(branch: str, packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Packages registered for a branch. Prefer unmerged ones: a branch name can recur."""
    same = [p for p in packages if p["branch"] == branch]
    return [p for p in same if p["status"] != "merged"] or same


def reasons_for(rel: str, branch: str, packages: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    if is_shared(rel):
        reasons.append(
            f"{rel} is a shared path (AGENTS.md). Changing it needs the `contract-change` "
            "label and integration-lead review, and contract, migration, spec or ADR "
            "changes also need an accepted ADR."
        )
    owners = owners_of(branch, packages) if branch else []
    if owners and not any(in_scope(rel, o["allowed_paths"]) for o in owners):
        ids = ", ".join(o["id"] for o in owners)
        reasons.append(
            f"{rel} is outside the allowed_paths of {ids} (branch {branch}). Stay inside the "
            "issue's allowed_paths, or have the work package updated first."
        )
    return reasons


def _git(cwd: str, *args: str) -> str:
    git = shutil.which("git")
    if git is None:
        return ""
    done = subprocess.run(  # nosec B603
        [git, "-C", cwd, *args], capture_output=True, text=True, timeout=5, check=False
    )
    return done.stdout.strip() if done.returncode == 0 else ""


def evaluate(payload: dict[str, Any]) -> list[str]:
    argument = PATH_ARGUMENT.get(str(payload.get("tool_name", "")))
    if argument is None:
        return []
    target = (payload.get("tool_input") or {}).get(argument)
    cwd = str(payload.get("cwd") or os.getcwd())
    if not isinstance(target, str) or not target:
        return []
    root = _git(cwd, "rev-parse", "--show-toplevel")
    if not root:
        return []
    absolute = target if os.path.isabs(target) else os.path.join(cwd, target)
    rel = os.path.relpath(os.path.realpath(absolute), os.path.realpath(root)).replace(os.sep, "/")
    if rel == ".." or rel.startswith("../"):
        return []
    registry = Path(root, WORKSTREAMS)
    packages = parse_packages(registry.read_text(encoding="utf-8")) if registry.is_file() else []
    return reasons_for(rel, _git(cwd, "symbolic-ref", "--short", "-q", "HEAD"), packages)


def main() -> int:
    mode = os.environ.get("FEL_PATH_GUARD", "ask")
    if mode == "off":
        return 0
    try:
        reasons = evaluate(json.load(sys.stdin))
    except Exception as error:  # fail open: a guard bug must never stall a session
        print(f"path_guard: skipped ({type(error).__name__}: {error})", file=sys.stderr)
        return 0
    if reasons:
        decision = "deny" if mode == "deny" else "ask"
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": decision,
                        "permissionDecisionReason": " ".join(reasons),
                    }
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
