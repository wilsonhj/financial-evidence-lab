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

# Line-based approximation of CommonMark link rendering, stdlib only. It skips
# fenced code (at any indent), indented code (4+ columns past the margin or the
# open list item's content), HTML comments, code spans, escaped brackets, and
# reference definitions that are unused or interrupt a paragraph; it strips
# blockquote markers and accepts <angle> and balanced-parenthesis targets.
# Exotic constructs (HTML blocks, lazy continuations, nested containers) may be
# misjudged: the job exists to catch unlinked new docs, not to validate Markdown.
QUOTE = re.compile(r"^ {0,3}> ?")
FENCE = re.compile(r"^ *(`{3,}|~{3,})")
ATX = re.compile(r"^ {0,3}#{1,6}(\s|$)")
SETEXT = re.compile(r"^ {0,3}(=+|-+) *$")
LIST_ITEM = re.compile(r"^( *)([-*+]|\d{1,9}[.)])( +|$)")
CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)
BRACKETS = re.compile(r"(?<!\\)\[((?:[^\[\]\\]|\\.)*)\]")
REFDEF = re.compile(r"^ *\[((?:[^\[\]\\]|\\.)+)\]:\s*(<[^>]*>|\S+)")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def mask_code_spans(text):
    """Mask inline code across a prose block, preserving line structure.

    CommonMark code spans may contain line endings, but cannot cross a blank
    line or a new block. Keep fences intact for prose_lines to discard them.
    Exact delimiter runs matter: one backtick cannot close two backticks.
    NUL placeholders keep code-only continuation lines inside their paragraph.
    """
    pending, result, fence = [], [], None
    depth = 0

    def flush():
        if not pending:
            return
        block = "\n".join(pending)
        result.append(CODE_SPAN.sub(
            lambda m: re.sub(r"[^\n]", lambda _: "\0", m.group()), block,
        ))
        pending.clear()

    for line in text.expandtabs(4).splitlines():
        content, quotes = line, 0
        while QUOTE.match(content):
            content, quotes = content[QUOTE.match(content).end():], quotes + 1
        marker = FENCE.match(content)
        if fence:
            result.append(line)
            if marker and marker.group(1)[0] == fence[0] \
                    and len(marker.group(1)) >= len(fence) \
                    and not content.strip().strip(fence[0]):
                fence = None
            continue
        if marker:
            flush()
            fence = marker.group(1)
            result.append(line)
            continue
        if not content.strip() or quotes != depth or ATX.match(content) \
                or SETEXT.match(content) or LIST_ITEM.match(content):
            flush()
        depth = quotes
        if not content.strip() or ATX.match(content) or SETEXT.match(content):
            # Headings are blocks themselves, including their inline code.
            result.append(CODE_SPAN.sub(lambda m: "\0" * len(m.group()), line))
        else:
            pending.append(line)
    flush()
    return "\n".join(result)


def prose_lines(text):
    """Yield (line, starts_block) for prose outside code and HTML comments.

    starts_block is true when the line follows a blank line, the start of the
    file or a blockquote, a heading, or a closing fence.
    """
    fence, comment, in_code, content = None, False, False, None
    blank, depth = True, 0
    for line in mask_code_spans(text).splitlines():
        quotes = 0
        while QUOTE.match(line):
            line, quotes = line[QUOTE.match(line).end():], quotes + 1
        if quotes != depth:
            blank, depth = True, quotes
        if fence:
            close = FENCE.match(line)
            if close and close.group(1)[0] == fence[0] \
                    and len(close.group(1)) >= len(fence) \
                    and not line.strip().strip(fence[0]):
                fence, blank = None, True
            continue
        if comment:
            end = line.find("-->")
            if end < 0:
                continue
            line, comment = line[end + 3:], False
        elif not line.strip():
            blank = True
            continue
        else:
            indent = len(line) - len(line.lstrip(" "))
            # Indented code: 4+ columns past the open list item's content (or
            # the margin) after a blank line or more code, list marker or not.
            if indent >= (content or 0) + 4 and (blank or in_code):
                in_code, blank = True, False
                continue
            in_code = False
            item = LIST_ITEM.match(line)
            if item:
                gap = len(item.group(3))
                content = (len(item.group(1)) + len(item.group(2))
                           + (gap if 1 <= gap <= 4 else 1))
            elif blank and indent < (content or 0):
                content = None
            if FENCE.match(line):
                fence, blank = FENCE.match(line).group(1), False
                continue
        # Comments open only in prose: drop code spans first.
        prose = ""
        while "<!--" in line:
            head, line = line.split("<!--", 1)
            prose += head
            if "-->" not in line:
                line, comment = "", True
                break
            line = line.split("-->", 1)[1]
        prose += line
        starts_block = blank
        blank = bool(ATX.match(prose) or SETEXT.match(prose))
        yield prose, starts_block


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
    defs, used, after_def = {}, set(), False
    blocks, pending = [], []
    for line, starts_block in prose_lines(text):
        if starts_block and pending:
            blocks.append("\n".join(pending))
            pending.clear()
        d = REFDEF.match(line)
        if d and (starts_block or after_def):
            defs.setdefault(label(d.group(1)), d.group(2).strip("<>"))
            after_def = True
            continue
        after_def = False
        pending.append(line)
    if pending:
        blocks.append("\n".join(pending))
    for block in blocks:
        block = block.replace("\\\\", "\0\0")  # \\ is a literal backslash
        for m in BRACKETS.finditer(block):
            rest = block[m.end():]
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
