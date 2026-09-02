"""Pure unit tests for `scripts/ci/shared_paths.py`. No network, no subprocess."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

import shared_paths

PATTERNS = [
    ".github/**",
    "specs/**",
    "packages/contracts/**",
    "db/migrations/**",
    "docs/handoff/workstreams.yaml",
    "docs/handoff/STATUS.md",
    "package.json",
    "pnpm-lock.yaml",
]


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        "specs/001-financial-evidence-lab/spec.md",
        "packages/contracts/openapi/openapi.yaml",
        "db/migrations/0010_add_column.sql",
        "docs/handoff/workstreams.yaml",
        "docs/handoff/STATUS.md",
        "package.json",
        "pnpm-lock.yaml",
    ],
)
def test_matches_shared_paths(path: str) -> None:
    assert shared_paths.match_shared_paths([path], PATTERNS) == [path]


@pytest.mark.parametrize(
    "path",
    [
        "apps/api/app/main.py",
        "evals/reporting/corpus_qa_render.py",
        "docs/handoff/README.md",
        "docs/handoff/workstreams.yamlx",  # not an exact match
        "package.jsonx",
        "scripts/ci/shared_paths.py",
    ],
)
def test_does_not_match_unrelated_paths(path: str) -> None:
    assert shared_paths.match_shared_paths([path], PATTERNS) == []


def test_double_star_matches_nested_directories() -> None:
    offenders = shared_paths.match_shared_paths(["specs/001/tasks/deep/nested/file.md"], PATTERNS)
    assert offenders == ["specs/001/tasks/deep/nested/file.md"]


def test_double_star_does_not_match_bare_prefix() -> None:
    # "specs" itself (no trailing segment) should not match "specs/**".
    assert shared_paths.match_shared_paths(["specs"], PATTERNS) == []


def test_multiple_files_only_offenders_returned() -> None:
    files = [
        "apps/api/app/main.py",
        "docs/handoff/STATUS.md",
        "db/migrations/0010_add_column.sql",
        "README.md",
    ]
    offenders = shared_paths.match_shared_paths(files, PATTERNS)
    assert offenders == ["docs/handoff/STATUS.md", "db/migrations/0010_add_column.sql"]


def test_load_shared_paths_reads_list(tmp_path: Path) -> None:
    ws = tmp_path / "workstreams.yaml"
    ws.write_text("shared_paths:\n  - a/**\n  - b.txt\n", encoding="utf-8")
    assert shared_paths.load_shared_paths(ws) == ["a/**", "b.txt"]


def test_load_shared_paths_missing_key(tmp_path: Path) -> None:
    ws = tmp_path / "workstreams.yaml"
    ws.write_text("other_key: true\n", encoding="utf-8")
    with pytest.raises(ValueError):
        shared_paths.load_shared_paths(ws)


def test_load_shared_paths_wrong_type(tmp_path: Path) -> None:
    ws = tmp_path / "workstreams.yaml"
    ws.write_text("shared_paths: not-a-list\n", encoding="utf-8")
    with pytest.raises(ValueError):
        shared_paths.load_shared_paths(ws)


def test_main_exits_1_without_label(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = tmp_path / "workstreams.yaml"
    ws.write_text("shared_paths:\n  - docs/handoff/STATUS.md\n", encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", io.StringIO("docs/handoff/STATUS.md\napps/api/x.py\n"))
    rc = shared_paths.main(["--workstreams", str(ws)])
    assert rc == 1


def test_main_exits_0_with_label(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = tmp_path / "workstreams.yaml"
    ws.write_text("shared_paths:\n  - docs/handoff/STATUS.md\n", encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", io.StringIO("docs/handoff/STATUS.md\napps/api/x.py\n"))
    rc = shared_paths.main(["--workstreams", str(ws), "--has-label"])
    assert rc == 0


def test_main_exits_0_when_no_shared_path_touched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "workstreams.yaml"
    ws.write_text("shared_paths:\n  - docs/handoff/STATUS.md\n", encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", io.StringIO("apps/api/x.py\n"))
    rc = shared_paths.main(["--workstreams", str(ws)])
    assert rc == 0
