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

LANE_BRANCH = (
    "agent/executive-architecture-docs"  # README.md, docs/architecture/**, workstreams.yaml
)


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
    listed = set(re.findall(r"^- `([^`]+)`", section, flags=re.M))
    listed |= set(
        re.findall(r"`(package-lock\.json|pnpm-lock\.yaml|pnpm-workspace\.yaml)`", section)
    )
    for item in listed:
        assert guard.is_shared(item.rstrip("/") + ("/x" if item.endswith("/") else "")), item


# --- parser parity on the real registry ---------------------------------------------------


def test_parser_matches_pyyaml_on_real_registry() -> None:
    yaml = pytest.importorskip("yaml")
    expected = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))["packages"]
    got = guard.parse_packages(REGISTRY.read_text(encoding="utf-8"))
    assert len(got) == len(expected) > 50
    for mine, theirs in zip(got, expected, strict=True):
        assert mine["id"] == theirs["id"]
        assert mine["branch"] == theirs.get("branch", "")
        assert mine["status"] == theirs.get("status", "")
        assert mine["allowed_paths"] == theirs.get("allowed_paths", []), theirs["id"]


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
    (root / "docs" / "handoff" / "workstreams.yaml").write_text(
        REGISTRY.read_text(encoding="utf-8"), encoding="utf-8"
    )
    _git(root, "init", "-q", "-b", "main")
    _git(
        root,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "i",
    )
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
    full_env = {**os.environ, **(env or {})}
    full_env.pop("FEL_PATH_GUARD", None) if env is None else None
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
