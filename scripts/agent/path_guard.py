#!/usr/bin/env python3
"""Claude Code PreToolUse hook: keep agent edits inside the work package's lane.

Enforces two rules from AGENTS.md at edit time, before the agent spends a cycle:

1. Shared paths (AGENTS.md "Shared paths") need the `contract-change` label and
   integration-lead review, so an edit to one asks first. The paths are the
   `shared_paths` inventory in `docs/handoff/workstreams.yaml` plus a built-in
   list that mirrors `.github/workflows/shared-paths.yml` (tests fail if either
   drifts), so the check still works when the registry is missing.
2. A branch listed in `docs/handoff/workstreams.yaml` may only edit that
   package's `allowed_paths`. Nothing in CI checks this today.

Edits to the guard itself (this script and the Claude Code settings files that
register it) always ask, so the hook cannot be removed through the tools it
inspects.

The hook never decides on its own authority: it answers `ask` (or `deny` when
FEL_PATH_GUARD=deny, for unattended runs) because both rules have legitimate
exceptions. It is fail-open: any error, unknown branch, or unreadable registry
exits 0 with no output, so a hook bug cannot stall a session. CI remains the
backstop. Only Edit, Write, MultiEdit and NotebookEdit are inspected; shell
commands that write files (sed -i, redirects, tee) are not.

Threat model: this prevents accidents, it is not a security boundary. The lane
follows whichever branch is checked out, so an agent can choose its own lane with
`git checkout -b`, and `CLAUDE.md` and the tests are not guarded. CI is the
enforcement point.

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
# The hook and the files that register it. An agent that could edit these
# without a prompt could switch the guard off before its next edit.
GUARD_FILES: frozenset[str] = frozenset(
    {
        "scripts/agent/path_guard.py",
        ".claude/settings.json",
        ".claude/settings.local.json",
    }
)
WORKSTREAMS = "docs/handoff/workstreams.yaml"
PATH_ARGUMENT = {
    "Edit": "file_path",
    "Write": "file_path",
    "MultiEdit": "file_path",
    "NotebookEdit": "notebook_path",
}


def is_shared(rel: str, registry_shared: list[str] | tuple[str, ...] = ()) -> bool:
    """True for the built-in CI list and for any registry `shared_paths` glob."""
    return rel in SHARED_EXACT or rel.startswith(SHARED_PREFIXES) or in_scope(rel, registry_shared)


def _strip_comment(raw: str) -> str:
    return re.sub(r"\s+#.*$", "", raw).rstrip()


def _scalar(value: str) -> str:
    """A YAML plain or quoted scalar, without its quotes."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _sections(text: str) -> dict[str, list[str]]:
    """Lines under each top-level key, comments and blank lines removed."""
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        top = re.match(r"^([A-Za-z_][\w-]*):", line)
        if top:
            current = sections.setdefault(top[1], [])
            continue
        if current is not None:
            current.append(line)
    return sections


def parse_shared_paths(text: str) -> list[str]:
    """The top-level `shared_paths` list of workstreams.yaml."""
    return [
        _scalar(entry[1])
        for line in _sections(text).get("shared_paths", [])
        if (entry := re.match(r"^  - (.+)$", line))
    ]


def parse_packages(text: str) -> list[dict[str, Any]]:
    """Read id, branch, status and allowed_paths from workstreams.yaml `packages`.

    A line parser, not a YAML library, so the hook runs under any python3. It
    accepts quoted or plain scalars and any key first in an entry; a test
    compares it against PyYAML on the real file.
    """
    packages: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    in_paths = False

    def field(key: str, value: str) -> None:
        nonlocal in_paths
        in_paths = False
        if cur is None:
            return
        if key in ("id", "branch", "status"):
            cur[key] = _scalar(value)
        elif key == "allowed_paths":
            rest = value.strip()
            if rest.startswith("["):
                items = rest.strip("[]").split(",")
                cur["allowed_paths"] = [_scalar(i) for i in items if i.strip()]
            else:
                in_paths = True

    for line in _sections(text).get("packages", []):
        item = re.match(r"^  - ([A-Za-z_][\w-]*):\s*(.*)$", line)
        if item:
            cur = {"id": "", "branch": "", "status": "", "allowed_paths": []}
            packages.append(cur)
            field(item[1], item[2])
            continue
        if cur is None:
            continue
        key = re.match(r"^    ([A-Za-z_][\w-]*):\s*(.*)$", line)
        if key:
            field(key[1], key[2])
            continue
        if in_paths:
            entry = re.match(r"^      - (.+)$", line)
            if entry:
                cur["allowed_paths"].append(_scalar(entry[1]))
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


def in_scope(rel: str, patterns: list[str] | tuple[str, ...]) -> bool:
    return any(_glob(p).match(rel) for p in patterns)


def owners_of(branch: str, packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Packages registered for a branch. Prefer unmerged ones: a branch name can recur."""
    same = [p for p in packages if p["branch"] == branch]
    return [p for p in same if p["status"] != "merged"] or same


def reasons_for(
    rel: str,
    branch: str,
    packages: list[dict[str, Any]],
    registry_shared: list[str] | tuple[str, ...] = (),
) -> list[str]:
    reasons: list[str] = []
    if rel in GUARD_FILES:
        reasons.append(
            f"{rel} is part of the path guard. Changing it can switch the guard off, "
            "so it always needs a person's confirmation."
        )
    if is_shared(rel, registry_shared):
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
    # These override `git -C` and would classify a worktree path against another checkout.
    env = os.environ.copy()
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_NAMESPACE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
    ):
        env.pop(key, None)
    done = subprocess.run(  # nosec B603
        [git, "-C", cwd, *args],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        env=env,
    )
    return done.stdout.strip() if done.returncode == 0 else ""


def canonical_case(path: str) -> str:
    """`path` with each existing component spelled as it is on disk.

    On a case-insensitive filesystem (default macOS APFS), `agents.md` opens
    `AGENTS.md`, and realpath() keeps the spelling it was given. A component
    that exists under a different spelling is replaced by the listed name; one
    that does not exist (a new file) is kept, so a case-sensitive filesystem,
    where `agents.md` really is a different file, is unaffected.
    """
    parts = os.path.normpath(path).split(os.sep)
    out = parts[0] + os.sep if parts[0] == "" else parts[0]
    for part in parts[1:]:
        if not part:
            continue
        candidate = os.path.join(out, part)
        if os.path.isdir(out) and os.path.lexists(candidate):
            try:
                names = os.listdir(out)
            except OSError:
                names = []
            if part not in names:
                folded = [n for n in names if n.casefold() == part.casefold()]
                if len(folded) == 1:
                    candidate = os.path.join(out, folded[0])
        out = candidate
    return out


def _nearest_dir(path: str) -> str:
    """The closest existing directory at or above `path`."""
    current = path
    while not os.path.isdir(current):
        parent = os.path.dirname(current)
        if parent == current:
            return current
        current = parent
    return current


def _reasons_for_absolute(absolute: str) -> list[str]:
    """Guard, shared-path, and lane reasons for one absolute form of a tool path.

    Empty when this form has no git root or escapes the checkout (`..`), so the
    caller can still judge the other form.
    """
    # The checkout that owns the file, not the session's: an edit inside a
    # worktree under .claude/worktrees/ belongs to that worktree's root,
    # branch and registry.
    owner = _nearest_dir(os.path.dirname(absolute))
    root = _git(owner, "rev-parse", "--show-toplevel")
    if not root:
        return []
    rel = os.path.relpath(absolute, canonical_case(os.path.realpath(root))).replace(os.sep, "/")
    if rel == ".." or rel.startswith("../"):
        return []
    registry = Path(root, WORKSTREAMS)
    text = registry.read_text(encoding="utf-8") if registry.is_file() else ""
    return reasons_for(
        rel,
        _git(owner, "symbolic-ref", "--short", "-q", "HEAD"),
        parse_packages(text),
        parse_shared_paths(text),
    )


def evaluate(payload: dict[str, Any]) -> list[str]:
    argument = PATH_ARGUMENT.get(str(payload.get("tool_name", "")))
    if argument is None:
        return []
    target = (payload.get("tool_input") or {}).get(argument)
    cwd = str(payload.get("cwd") or os.getcwd())
    if not isinstance(target, str) or not target:
        return []
    raw = target if os.path.isabs(target) else os.path.join(cwd, target)
    # Ancestor symlinks are resolved; the final component is kept, so a symlink
    # named package.json is still judged as package.json. The fully resolved
    # path is judged too. A form that leaves the repo is skipped on its own.
    named = canonical_case(
        os.path.join(os.path.realpath(os.path.dirname(raw)), os.path.basename(raw))
    )
    resolved = canonical_case(os.path.realpath(raw))
    forms = [named]
    if resolved != named:
        forms.append(resolved)
    reasons: list[str] = []
    for absolute in forms:
        for reason in _reasons_for_absolute(absolute):
            if reason not in reasons:
                reasons.append(reason)
    return reasons


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
