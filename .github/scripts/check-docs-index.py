#!/usr/bin/env python3
"""Fail when a tracked Markdown file is not reachable from docs/README.md.

docs/README.md claims to index every Markdown document. Starting there, follow
relative Markdown links ([text](path), and [ref]: path when [ref] is used)
through every reachable .md file, at any depth, so sub-indexes such as
docs/decisions/README.md count. URLs, bare #anchors, escaped brackets, HTML
comments, code spans, and fenced or indented code are ignored. A link to a
directory reaches that directory's README.md when one exists.

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
# every entry needs a reason. Patterns use fnmatch, and a pattern only matches
# paths with the same number of "/" separators, so * never crosses a directory.
EXCLUDE = {
    # docs/README.md links these folders as directories ("Spec Kit skills",
    # "Spec Kit templates"); neither has a README.md to land on.
    ".agents/skills/*/SKILL.md": "indexed as a directory in docs/README.md",
    ".specify/templates/*.md": "indexed as a directory in docs/README.md",
    # Pointer stubs: docs/README.md "Specifications" names them and says never
    # to cite them, so linking them would contradict the index.
    "SPEC.md": "root pointer stub, mentioned not linked",
    "PLAN.md": "root pointer stub, mentioned not linked",
    "TASKS.md": "root pointer stub, mentioned not linked",
}
# Untracked trees (node_modules, .venv) need no entry: only git ls-files counts.

# A line-based approximation of CommonMark: enough to skip text that does not
# render as a link, without a Markdown parser dependency.
COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.S)
FENCE = re.compile(r"^ *(`{3,}|~{3,})")
LIST_ITEM = re.compile(r"^( *)([-*+]|\d{1,9}[.)])( +|$)")
CODE_SPAN = re.compile(r"(`+).+?\1")
BRACKETS = re.compile(r"(?<!\\)\[((?:[^\[\]\\]|\\.)*)\]")
REFDEF = re.compile(r"^ {0,3}\[((?:[^\[\]\\]|\\.)+)\]:\s*(<[^>]*>|\S+)")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def prose_lines(text):
    """Yield lines outside HTML comments, fenced and indented code blocks."""
    text = COMMENT.sub(lambda m: "\n" * m.group().count("\n"), text)
    fence, blank, in_code, content = None, True, False, None
    for line in text.expandtabs(4).splitlines():
        indent = len(line) - len(line.lstrip(" "))
        if fence:
            close = FENCE.match(line)
            if close and close.group(1)[0] == fence[0] \
                    and len(close.group(1)) >= len(fence) \
                    and not line.strip().strip(fence[0]):
                fence = None
            continue
        if not line.strip():
            blank = True
            continue
        item = LIST_ITEM.match(line)
        # Indented code: 4+ columns past the enclosing list item's content
        # (or the margin), after a blank line or more indented code.
        if (indent >= (content or 0) + 4 and (blank or in_code)
                and not item):
            in_code, blank = True, False
            continue
        in_code = False
        if FENCE.match(line):
            fence, blank = FENCE.match(line).group(1), False
            continue
        if item:
            gap = len(item.group(3))
            content = (len(item.group(1)) + len(item.group(2))
                       + (gap if 1 <= gap <= 4 else 1))
        elif blank and indent < (content or 0):
            content = None
        blank = False
        yield line


def destination(rest):
    """Return the link destination at the start of rest (after "](")."""
    rest = rest.lstrip()
    if rest.startswith("<"):
        end = rest.find(">")
        return rest[1:end] if end > 0 else None
    depth, i = 0, 0
    while i < len(rest):
        c = rest[i]
        if c == "\\":
            i += 1
        elif c == "(":
            depth += 1
        elif c == ")":
            if depth == 0:
                break
            depth -= 1
        elif c.isspace():
            break
        i += 1
    return rest[:i] or None


def label(text):
    return " ".join(text.lower().split())


def links(text):
    """Yield raw targets of inline links and of reference links in use."""
    defs, used = {}, set()
    for line in prose_lines(text):
        d = REFDEF.match(line)
        if d:
            defs.setdefault(label(d.group(1)), d.group(2).strip("<>"))
            continue
        line = CODE_SPAN.sub("", line)
        for m in BRACKETS.finditer(line):
            rest = line[m.end():]
            if rest.startswith("("):
                target = destination(rest[1:])
                if target:
                    yield target
            elif rest.startswith("[") and not rest.startswith("[]"):
                continue  # [text][label]: the next match is the label
            else:
                used.add(label(m.group(1)))  # [label][] or shortcut [label]
    yield from (t for k, t in defs.items() if k in used)


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
        if not any(p.count("/") == pat.count("/")
                   and fnmatch.fnmatchcase(p, pat) for pat in EXCLUDE)
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
