#!/usr/bin/env python3
"""Fail when a tracked Markdown file is not reachable from docs/README.md.

docs/README.md claims to index every Markdown document. Starting there, follow
relative Markdown links ([text](path) and [ref]: path) through every reachable
.md file, at any depth, so sub-indexes such as docs/decisions/README.md count.
URLs, bare #anchors, code spans and fenced code blocks are ignored. A link to
a directory reaches that directory's README.md when one exists.

Usage: check-docs-index.py [repo-root]   (default: current directory)
"""
import fnmatch
import os
import re
import subprocess
import sys
from urllib.parse import unquote

START = "docs/README.md"

# Tracked Markdown that is deliberately not reachable by link. Keep this short;
# every entry needs a reason. Patterns use fnmatch, where * also matches "/".
EXCLUDE = {
    # docs/README.md links these folders as directories ("Spec Kit skills",
    # "Spec Kit templates"); neither has a README.md to land on.
    ".agents/skills/*": "indexed as a directory in docs/README.md",
    ".specify/templates/*": "indexed as a directory in docs/README.md",
    # Pointer stubs: docs/README.md "Specifications" names them and says never
    # to cite them, so linking them would contradict the index.
    "SPEC.md": "root pointer stub, mentioned not linked",
    "PLAN.md": "root pointer stub, mentioned not linked",
    "TASKS.md": "root pointer stub, mentioned not linked",
}
# Untracked trees (node_modules, .venv) need no entry: only git ls-files counts.

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
CODE_SPAN = re.compile(r"(`+).*?\1")
INLINE = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'(][^)]*)?\)")
REFDEF = re.compile(r"^ {0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def links(text):
    """Yield raw link targets outside code fences and code spans."""
    fence = None
    for line in text.splitlines():
        m = FENCE.match(line)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        line = CODE_SPAN.sub("", line)
        yield from INLINE.findall(line)
        yield from REFDEF.findall(line)


def resolve(source, target, root, tracked):
    """Return the tracked .md path a link reaches, or None."""
    if SCHEME.match(target) or target.startswith("#"):
        return None
    target = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not target:
        return None
    base = "" if target.startswith("/") else os.path.dirname(source)
    path = os.path.normpath(os.path.join(base, target.lstrip("/")))
    if os.path.isdir(os.path.join(root, path)):
        path = os.path.join(path, "README.md")
    return path if path in tracked else None


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    out = subprocess.run(
        ["git", "-C", root, "ls-files", "-z", "--", "*.md"],
        check=True, capture_output=True, text=True,
    ).stdout
    tracked = set(filter(None, out.split("\0")))
    if START not in tracked:
        print(f"{START} is not tracked", file=sys.stderr)
        return 1

    reached, queue = {START}, [START]
    while queue:
        source = queue.pop()
        with open(os.path.join(root, source), encoding="utf-8") as f:
            text = f.read()
        for target in links(text):
            path = resolve(source, target, root, tracked)
            if path and path not in reached:
                reached.add(path)
                queue.append(path)

    missing = sorted(
        p for p in tracked - reached
        if not any(fnmatch.fnmatchcase(p, pat) for pat in EXCLUDE)
    )
    if missing:
        print(f"Not reachable from {START} (add an index row or link):")
        for p in missing:
            print(f"  {p}")
        return 1
    print(f"OK: {len(reached)} Markdown files reachable from {START}, "
          f"{len(tracked) - len(reached)} excluded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
