"""Tests for scripts/agent/path_guard.py (run: pytest scripts/agent/tests)."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
HOOK = REPO / "scripts" / "agent" / "path_guard.py"
REGISTRY = REPO / "docs" / "handoff" / "workstreams.yaml"
CI_WORKFLOW = REPO / ".github" / "workflows" / "shared-paths.yml"
SETTINGS = REPO / ".claude" / "settings.json"
GITIGNORE = REPO / ".gitignore"

spec = importlib.util.spec_from_file_location("path_guard", HOOK)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

# The subprocess tests run against this registry, not the live one, so editing
# docs/handoff/workstreams.yaml cannot break them.
LANE_BRANCH = "agent/lane"
FIXTURE_REGISTRY = """\
version: 2
shared_paths:
  - .github/**
  - .agents/**
  - docs/handoff/workstreams.yaml
  - AGENTS.md
  - .gitignore
  - tsconfig.json
packages:
  - id: LANE
    branch: agent/lane
    status: active
    allowed_paths:
      - README.md
      - docs/architecture/**
      - docs/handoff/workstreams.yaml
"""


# --- the two hand-maintained copies must not drift -------------------------------------------


def _ci_literal(name: str) -> str:
    return re.search(rf"{name}='([^']*)'", CI_WORKFLOW.read_text(encoding="utf-8")).group(1)  # type: ignore[union-attr]


def _alternatives(regex: str) -> set[str]:
    inner = regex.removeprefix("^(").removesuffix(")$").removesuffix(")")
    return {part.replace("\\.", ".") for part in inner.split("|")}


def test_shared_list_matches_ci_workflow() -> None:
    assert set(guard.SHARED_PREFIXES) == _alternatives(_ci_literal("shared_prefix"))
    assert set(guard.SHARED_EXACT) == _alternatives(_ci_literal("shared_exact"))


def test_shared_list_matches_agents_md() -> None:
    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    section = agents.split("## Shared paths", 1)[1].split("Every change to a shared path", 1)[0]
    # Every backticked path in the section, including the inline root-config
    # bullet; `contract-change` is a label, not a path.
    listed = set(re.findall(r"`([^`]+)`", section)) - {"contract-change"}
    assert {"package.json", "pyproject.toml", "Makefile", "AGENTS.md"} <= listed
    for item in listed:
        assert guard.is_shared(item.rstrip("/") + ("/x" if item.endswith("/") else "")), item


# --- parser parity on the real registry ---------------------------------------------------


def test_parser_matches_pyyaml_on_real_registry() -> None:
    yaml = pytest.importorskip("yaml")
    expected = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))["packages"]
    got = guard.parse_packages(REGISTRY.read_text(encoding="utf-8"))
    assert len(got) == len(expected) > 0
    for mine, theirs in zip(got, expected, strict=True):
        assert mine["id"] == theirs["id"]
        assert mine["branch"] == theirs.get("branch", "")
        assert mine["status"] == theirs.get("status", "")
        assert mine["allowed_paths"] == theirs.get("allowed_paths", []), theirs["id"]


def test_shared_paths_parser_matches_pyyaml_on_real_registry() -> None:
    yaml = pytest.importorskip("yaml")
    text = REGISTRY.read_text(encoding="utf-8")
    assert guard.parse_shared_paths(text) == yaml.safe_load(text)["shared_paths"]


def test_every_registry_shared_path_is_shared() -> None:
    registry_shared = guard.parse_shared_paths(REGISTRY.read_text(encoding="utf-8"))
    assert ".gitignore" in registry_shared and ".agents/**" in registry_shared
    for pattern in registry_shared:
        sample = pattern.replace("**", "x/y").replace("*", "z")
        assert guard.is_shared(sample, registry_shared), pattern
        assert guard.reasons_for(sample, "main", [], registry_shared), pattern


def test_parser_reads_quoted_values_and_any_first_key() -> None:
    text = """\
packages:
  - issue: 12
    id: "Q"
    branch: "agent/quoted"
    status: 'active'
    allowed_paths: ["apps/api/**", 'x.md']
  - id: R
    branch: agent/r # trailing comment
    allowed_paths:
      - "docs/**"
"""
    got = guard.parse_packages(text)
    assert [(p["id"], p["branch"], p["status"]) for p in got] == [
        ("Q", "agent/quoted", "active"),
        ("R", "agent/r", ""),
    ]
    assert got[0]["allowed_paths"] == ["apps/api/**", "x.md"]
    assert got[1]["allowed_paths"] == ["docs/**"]
    assert len(guard.reasons_for("apps/web/a.tsx", "agent/quoted", got)) == 1
    assert guard.reasons_for("apps/api/a.py", "agent/quoted", got) == []


def test_parser_ignores_list_items_outside_packages() -> None:
    text = "shared_path_exceptions:\n  - adr: ADR-0003\n    branch: nope\npackages:\n  - id: P\n"
    assert [p["id"] for p in guard.parse_packages(text)] == ["P"]


# --- decision logic -----------------------------------------------------------------------

PACKAGES: list[dict[str, Any]] = [
    {"id": "A", "branch": "agent/a", "status": "active", "allowed_paths": ["apps/api/**", "x.md"]},
    {"id": "B-old", "branch": "agent/dup", "status": "merged", "allowed_paths": ["old/**"]},
    {"id": "B-new", "branch": "agent/dup", "status": "active", "allowed_paths": ["new/**"]},
]


@pytest.mark.parametrize(
    ("rel", "branch", "expect_reasons"),
    [
        ("apps/api/app/main.py", "agent/a", 0),
        ("x.md", "agent/a", 0),
        ("apps/web/page.tsx", "agent/a", 1),
        ("apps/api", "agent/a", 1),  # a bare directory is not an editable file
        ("apps/apix/y.py", "agent/a", 1),
        ("AGENTS.md", "agent/a", 2),
        ("docs/decisions/ADR-0099.md", "main", 1),
        ("apps/web/page.tsx", "main", 0),
        ("apps/web/page.tsx", "", 0),
        ("new/f.py", "agent/dup", 0),
        ("old/f.py", "agent/dup", 1),
    ],
)
def test_reasons(rel: str, branch: str, expect_reasons: int) -> None:
    assert len(guard.reasons_for(rel, branch, PACKAGES)) == expect_reasons


@pytest.mark.parametrize(
    "rel", ["scripts/agent/path_guard.py", ".claude/settings.json", ".claude/settings.local.json"]
)
def test_guard_files_always_ask(rel: str) -> None:
    reasons = guard.reasons_for(rel, "main", PACKAGES)
    assert reasons and "path guard" in reasons[0]


def test_canonical_case_uses_the_on_disk_spelling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "AGENTS.md").write_text("x", encoding="utf-8")
    real_lexists = os.path.lexists

    def case_insensitive_lexists(path: str) -> bool:
        parent, name = os.path.split(path)
        if real_lexists(path):
            return True
        return os.path.isdir(parent) and any(
            n.casefold() == name.casefold() for n in os.listdir(parent)
        )

    monkeypatch.setattr(guard.os.path, "lexists", case_insensitive_lexists)
    assert guard.canonical_case(str(tmp_path / "agents.md")) == str(tmp_path / "AGENTS.md")
    assert guard.canonical_case(str(tmp_path / "DOCS" / "new.md")) == str(
        tmp_path / "docs" / "new.md"
    )


def test_canonical_case_keeps_a_new_file_on_a_case_sensitive_filesystem(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("x", encoding="utf-8")
    assert guard.canonical_case(str(tmp_path / "agents.md")) == str(tmp_path / "agents.md")


def test_single_star_glob_stays_in_one_segment() -> None:
    assert guard.in_scope(
        "evals/harness/reader_prod_smoke_x.py", ["evals/harness/reader_prod_smoke*.py"]
    )
    assert not guard.in_scope(
        "evals/harness/reader_prod_smoke_a/b.py", ["evals/harness/reader_prod_smoke*.py"]
    )


# --- the hook as Claude Code calls it: JSON on stdin, JSON on stdout ----------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "docs" / "handoff").mkdir(parents=True)
    (root / "docs" / "handoff" / "workstreams.yaml").write_text(FIXTURE_REGISTRY, encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")  # committed, so a worktree checks the registry out too
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "i")
    return root


def run_hook(
    cwd: Path,
    tool: str,
    path: str | None,
    *,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    payload = (
        stdin
        if stdin is not None
        else json.dumps(
            {
                "cwd": str(cwd),
                "hook_event_name": "PreToolUse",
                "tool_name": tool,
                "tool_input": {key: path} if path is not None else {},
            }
        )
    )
    full_env = dict(os.environ)
    full_env.pop("FEL_PATH_GUARD", None)  # a developer's own setting must not leak in
    full_env.update(env or {})
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


def decision(done: subprocess.CompletedProcess[str]) -> str | None:
    assert done.returncode == 0
    if not done.stdout.strip():
        return None
    out = json.loads(done.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    return str(out["permissionDecision"])


def test_in_lane_edit_is_silent(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", LANE_BRANCH)
    assert decision(run_hook(repo, "Edit", str(repo / "docs/architecture/overview.md"))) is None
    assert decision(run_hook(repo, "Write", "README.md")) is None  # relative to cwd


def test_out_of_lane_edit_asks(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", LANE_BRANCH)
    done = run_hook(repo, "Edit", str(repo / "apps/api/app/main.py"))
    assert decision(done) == "ask"
    assert (
        "allowed_paths" in json.loads(done.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    )


def test_shared_path_asks_even_when_in_lane(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", LANE_BRANCH)  # lists workstreams.yaml in allowed_paths
    done = run_hook(repo, "MultiEdit", str(repo / "docs/handoff/workstreams.yaml"))
    assert decision(done) == "ask"
    reason = json.loads(done.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "contract-change" in reason and "allowed_paths" not in reason


def test_shared_path_asks_on_main_but_other_paths_do_not(repo: Path) -> None:
    assert decision(run_hook(repo, "Write", "AGENTS.md")) == "ask"
    assert decision(run_hook(repo, "Write", "apps/web/page.tsx")) is None


def test_notebook_edit_is_inspected(repo: Path) -> None:
    assert decision(run_hook(repo, "NotebookEdit", str(repo / "db/migrations/x.ipynb"))) == "ask"


def test_deny_mode_for_unattended_runs(repo: Path) -> None:
    assert decision(run_hook(repo, "Write", "AGENTS.md", env={"FEL_PATH_GUARD": "deny"})) == "deny"


def test_off_mode(repo: Path) -> None:
    assert decision(run_hook(repo, "Write", "AGENTS.md", env={"FEL_PATH_GUARD": "off"})) is None


def test_other_tools_and_outside_repo_are_ignored(repo: Path, tmp_path: Path) -> None:
    assert decision(run_hook(repo, "Bash", "AGENTS.md")) is None
    assert decision(run_hook(repo, "Write", str(tmp_path / "elsewhere" / "AGENTS.md"))) is None
    _git(repo, "checkout", "-q", "-b", LANE_BRANCH)  # an out-of-repo file is not "out of lane"
    assert decision(run_hook(repo, "Write", str(tmp_path / "elsewhere" / "notes.py"))) is None


def test_dotdot_cannot_launder_a_shared_path(repo: Path) -> None:
    (repo / "apps").mkdir()
    assert decision(run_hook(repo, "Write", "apps/../AGENTS.md")) == "ask"


def test_symlink_into_shared_path_is_caught(repo: Path) -> None:
    (repo / "docs" / "alias").symlink_to(repo / "docs" / "decisions", target_is_directory=True)
    (repo / "docs" / "decisions").mkdir()
    assert decision(run_hook(repo, "Write", "docs/alias/ADR-0100.md")) == "ask"


def test_symlink_named_package_json_asks_for_the_named_path(repo: Path) -> None:
    """The name the tool used stays a shared path when only the final component is a symlink."""
    (repo / "NOTES.md").write_text("notes\n", encoding="utf-8")
    (repo / "package.json").symlink_to("NOTES.md")
    done = run_hook(repo, "Edit", "package.json")
    assert decision(done) == "ask"
    reason = json.loads(done.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "package.json is a shared path" in reason


def test_in_lane_symlink_to_agents_md_asks(repo: Path) -> None:
    """An allowed name whose target is AGENTS.md is still a shared-path edit."""
    _git(repo, "checkout", "-q", "-b", LANE_BRANCH)
    (repo / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
    (repo / "README.md").symlink_to("AGENTS.md")
    done = run_hook(repo, "Edit", "README.md")
    assert decision(done) == "ask"
    reason = json.loads(done.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "AGENTS.md is a shared path" in reason


def test_git_dir_and_work_tree_do_not_hide_a_worktree_shared_path(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GIT_DIR and GIT_WORK_TREE must not override git -C for the worktree under edit.

    monkeypatch restores both variables after the test so later cases keep a clean environment.
    """
    other = tmp_path / "other-checkout"
    other.mkdir()
    _git(other, "init", "-q", "-b", "main")
    worktree = repo / ".claude" / "worktrees" / "lane"
    _git(repo, "worktree", "add", "-q", "-b", LANE_BRANCH, str(worktree))
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    done = run_hook(repo, "Edit", str(worktree / "AGENTS.md"))
    assert decision(done) == "ask"
    reason = json.loads(done.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "AGENTS.md is a shared path" in reason


def test_detached_head_checks_shared_only(repo: Path) -> None:
    _git(repo, "checkout", "-q", "--detach")
    assert decision(run_hook(repo, "Write", "apps/web/page.tsx")) is None
    assert decision(run_hook(repo, "Write", "AGENTS.md")) == "ask"


@pytest.mark.parametrize("stdin", ["", "not json", "[]", '{"tool_name": "Edit"}', '{"cwd": 5}'])
def test_fails_open_on_bad_input(repo: Path, stdin: str) -> None:
    done = run_hook(repo, "Edit", None, stdin=stdin)
    assert done.returncode == 0 and done.stdout.strip() == ""


def test_fails_open_when_registry_is_missing_or_garbled(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", LANE_BRANCH)
    registry = repo / "docs/handoff/workstreams.yaml"
    registry.write_text("\x00\x01 garbage: [", encoding="utf-8")
    assert decision(run_hook(repo, "Write", "apps/web/page.tsx")) is None
    registry.unlink()
    assert decision(run_hook(repo, "Write", "apps/web/page.tsx")) is None
    assert decision(run_hook(repo, "Write", "AGENTS.md")) == "ask"  # shared list needs no registry


def test_fails_open_when_git_is_unavailable(repo: Path, tmp_path: Path) -> None:
    empty = tmp_path / "no-git"
    empty.mkdir()
    done = run_hook(repo, "Write", "AGENTS.md", env={"PATH": str(empty)})
    assert done.returncode == 0 and done.stdout.strip() == ""


# --- the wiring: settings.json command and .gitignore ---------------------------------------


def _settings_entry() -> dict[str, Any]:
    entry = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]
    assert isinstance(entry, dict)
    return entry


def _run_command(project_dir: Path | None, payload: str) -> subprocess.CompletedProcess[str]:
    """Run the settings.json command through a shell, as Claude Code does."""
    env = {k: v for k, v in os.environ.items() if k not in {"CLAUDE_PROJECT_DIR", "FEL_PATH_GUARD"}}
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    command = _settings_entry()["hooks"][0]["command"]
    return subprocess.run(
        ["sh", "-c", command], input=payload, capture_output=True, text=True, env=env, check=False
    )


def test_settings_matcher_covers_every_inspected_tool() -> None:
    assert set(_settings_entry()["matcher"].split("|")) == set(guard.PATH_ARGUMENT)


def test_command_is_fail_open_when_the_script_is_missing(tmp_path: Path) -> None:
    # Exit 2 is the blocking code for PreToolUse: a missing script must not block edits.
    for project_dir in (tmp_path, None):
        done = _run_command(project_dir, "{}")
        assert done.returncode == 0 and done.stdout.strip() == ""


def test_command_is_fail_open_when_the_script_crashes(tmp_path: Path) -> None:
    script = tmp_path / "scripts" / "agent" / "path_guard.py"
    script.parent.mkdir(parents=True)
    script.write_text("import sys\nsys.exit(2)\n", encoding="utf-8")
    done = _run_command(tmp_path, "{}")
    assert done.returncode == 0


def test_command_still_runs_the_hook_when_the_script_exists(repo: Path) -> None:
    script_dir = repo / "scripts" / "agent"
    script_dir.mkdir(parents=True)
    shutil.copy(HOOK, script_dir / "path_guard.py")
    payload = json.dumps(
        {"cwd": str(repo), "tool_name": "Write", "tool_input": {"file_path": "AGENTS.md"}}
    )
    done = _run_command(repo, payload)
    assert done.returncode == 0
    assert json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"] == "ask"


@pytest.mark.parametrize(
    ("path", "ignored"),
    [
        (".claude/settings.json", False),
        (".claude/settings.local.json", True),
        (".claude/worktrees/w1/AGENTS.md", True),
        ("apps/web/.claude/settings.local.json", True),
        ("apps/web/.claude/settings.json", True),
    ],
)
def test_gitignore_tracks_only_the_root_claude_settings(
    tmp_path: Path, path: str, ignored: bool
) -> None:
    root = tmp_path / "ignore-repo"
    root.mkdir()
    _git(root, "init", "-q")
    shutil.copy(GITIGNORE, root / ".gitignore")
    done = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", path], check=False)
    assert (done.returncode == 0) is ignored


def test_registry_shared_path_asks(repo: Path) -> None:
    assert decision(run_hook(repo, "Write", ".gitignore")) == "ask"
    assert decision(run_hook(repo, "Edit", ".agents/skills/x/SKILL.md")) == "ask"
    assert decision(run_hook(repo, "Edit", "tsconfig.json")) == "ask"


def test_guard_files_ask_through_the_hook(repo: Path) -> None:
    for rel in ("scripts/agent/path_guard.py", ".claude/settings.json"):
        assert decision(run_hook(repo, "Edit", rel)) == "ask", rel


def test_worktree_edit_uses_the_worktree_root_and_branch(repo: Path, tmp_path: Path) -> None:
    worktree = repo / ".claude" / "worktrees" / "lane"
    _git(repo, "worktree", "add", "-q", "-b", LANE_BRANCH, str(worktree))
    # The session runs in the main checkout on `main`; the edits land in the worktree.
    out_of_lane = run_hook(repo, "Edit", str(worktree / "apps" / "api" / "main.py"))
    assert decision(out_of_lane) == "ask"
    assert (
        "allowed_paths"
        in json.loads(out_of_lane.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    )
    assert decision(run_hook(repo, "Edit", str(worktree / "AGENTS.md"))) == "ask"
    assert (
        decision(run_hook(repo, "Edit", str(worktree / "docs" / "architecture" / "a.md"))) is None
    )
