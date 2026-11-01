#!/usr/bin/env bash
set -euo pipefail

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

script_dir=$(cd "$(dirname "$0")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
check=$script_dir/check-docs-index.py
workflow=$repo_root/.github/workflows/docs.yml

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

repo=$(mktemp -d)
trap 'rm -rf "$repo"' EXIT

git -C "$repo" init -q -b main
mkdir -p "$repo/docs/sub" "$repo/pkg" "$repo/.agents/skills/x"
cat > "$repo/docs/README.md" <<'EOF'
# Index

- [Sub-index](sub/README.md)
- [Package](../pkg/)
- [External](https://example.com/orphan.md) and [anchor](#index)
- `[in a code span](orphan.md)`

```md
[in a fence](orphan.md)
```
EOF
printf '# Sub\n\n[Leaf](leaf.md#top)\n' > "$repo/docs/sub/README.md"
printf '# Leaf\n' > "$repo/docs/sub/leaf.md"
printf '# Package\n' > "$repo/pkg/README.md"
printf '# Skill\n' > "$repo/.agents/skills/x/SKILL.md"
git -C "$repo" add -A

run_check() {
  python3 "$check" "$repo"
}

# Indexed through a sub-index, a directory link, and an exclusion: pass.
out=$(run_check) || fail "expected pass on an indexed tree. Output: $out"

# Linked only from a URL, a code span, or a fence: still unindexed, so fail.
printf '# Orphan\n' > "$repo/docs/orphan.md"
git -C "$repo" add docs/orphan.md
if out=$(run_check); then
  fail "expected failure for unindexed docs/orphan.md. Output: $out"
fi
grep -qx '  docs/orphan.md' <<< "$out" || fail "docs/orphan.md not reported. Output: $out"

# Untracked Markdown is ignored.
git -C "$repo" rm -q --cached docs/orphan.md
out=$(run_check) || fail "untracked docs/orphan.md must be ignored. Output: $out"

# Indexing it from the sub-index makes the check pass again.
git -C "$repo" add docs/orphan.md
printf -- '- [Orphan](../orphan.md)\n' >> "$repo/docs/sub/README.md"
out=$(run_check) || fail "expected pass once docs/orphan.md is linked. Output: $out"

# Each snippet links docs/orphan.md only in a way that does not render as a
# link, so docs/orphan.md must still be reported.
index=$(cat "$repo/docs/README.md")
printf '# Sub\n\n[Leaf](leaf.md#top)\n' > "$repo/docs/sub/README.md"
expect_unindexed() {
  local name=$1 snippet=$2 out
  printf '%s\n\n%s\n' "$index" "$snippet" > "$repo/docs/README.md"
  if out=$(run_check); then
    fail "$name: docs/orphan.md must stay unindexed. Output: $out"
  fi
  grep -qx '  docs/orphan.md' <<< "$out" || fail "$name: orphan not reported. Output: $out"
}
expect_indexed() {
  local name=$1 snippet=$2 out
  printf '%s\n\n%s\n' "$index" "$snippet" > "$repo/docs/README.md"
  out=$(run_check) || fail "$name: docs/orphan.md should be reached. Output: $out"
}
expect_unindexed "html comment" $'<!--\n[x](orphan.md)\n-->'
expect_unindexed "inline comment" 'Text <!-- [x](orphan.md) --> more.'
expect_unindexed "indented code" $'Para.\n\n    [x](orphan.md)'
expect_unindexed "indented fence in list" $'1. Step\n\n    ```md\n    [x](orphan.md)\n    ```'
expect_unindexed "escaped link" '\[x](orphan.md)'
expect_unindexed "unused reference" '[u]: orphan.md'
expect_unindexed "indented code after heading" $'# Heading\n    [x](orphan.md)'
expect_unindexed "indented code after setext" $'Title\n=====\n    [x](orphan.md)'
expect_unindexed "indented code after fence" $'```\ncode\n```\n    [x](orphan.md)'
expect_unindexed "indented code in quote" $'> Para.\n>\n>     [x](orphan.md)'
expect_unindexed "fence in quote" $'> ```\n> [x](orphan.md)\n> ```'
expect_unindexed "definition interrupting paragraph" $'See [u].\n[u]: orphan.md'
expect_unindexed "deep list marker as code" $'Para.\n\n        - [x](orphan.md)'
expect_unindexed "multiline code span" $'`example\n[x](orphan.md)\ncode`'
expect_unindexed "multiline code span containing comment opener" $'`example\n<!-- [x](orphan.md)\ncode`'
expect_unindexed "multiline double-backtick span" $'``example `\n[x](orphan.md)\ncode``'
expect_indexed "multiline inline destination" $'[x](\n  orphan.md\n)'
expect_indexed "multiline label with code-only line" $'[the\n`orphan`\n page](orphan.md)'
expect_indexed "multiline inline label" $'[the\n orphan](orphan.md)'
expect_indexed "shorter backtick run is not a closer" $'``example\n`\n[x](orphan.md)'
expect_indexed "longer backtick run is not a closer" $'`example\n``\n[x](orphan.md)'
expect_indexed "unmatched backtick" $'`example\n[x](orphan.md)'
expect_indexed "code spans cannot cross paragraphs" $'`example\n\n[x](orphan.md)\ncode`'
expect_indexed "code spans cannot cross fences" $'`example\n```\ncode\n```\n[x](orphan.md)\ncode`'
expect_indexed "comment opener in code span" 'Write `<!--` then [x](orphan.md).'
expect_indexed "comment opener in fence" $'```html\n<!--\n```\n\n[x](orphan.md)'
expect_indexed "escaped backslash" '\\[x](orphan.md)'
expect_indexed "consecutive definitions" $'See [u].\n\n[a]: sub/README.md\n[u]: orphan.md'
expect_indexed "indented list continuation" $'- Item\n\n    [x](orphan.md)'
expect_indexed "used reference" $'See [the orphan][o].\n\n[o]: orphan.md'
expect_indexed "shortcut reference" $'See [Orphan].\n\n[orphan]: <orphan.md>'
mv "$repo/docs/orphan.md" "$repo/docs/o (1).md"
git -C "$repo" add -A docs
expect_indexed "angle link with spaces" '[x](<o (1).md>)'
git -C "$repo" mv "docs/o (1).md" "docs/o(1).md"
expect_indexed "balanced parentheses" '[x](o(1).md)'

# Exclusions cover exactly the intended depth.
printf '%s\n' "$index" > "$repo/docs/README.md"
git -C "$repo" rm -q --cached "docs/o(1).md"
mkdir -p "$repo/.agents/skills/x/deep" "$repo/.specify/templates/sub"
printf '# Deep\n' > "$repo/.agents/skills/x/deep/NOTES.md"
printf '# Sub\n' > "$repo/.specify/templates/sub/t.md"
git -C "$repo" add -A .agents .specify
if out=$(run_check); then
  fail "files below the excluded depth must not be exempt. Output: $out"
fi
grep -qx '  .agents/skills/x/deep/NOTES.md' <<< "$out" || fail "deep skill file not reported. Output: $out"
grep -qx '  .specify/templates/sub/t.md' <<< "$out" || fail "nested template not reported. Output: $out"

grep -F -q 'check-docs-index.py' "$workflow" \
  || fail "docs.yml does not run check-docs-index.py"

echo "PASS"
echo "indexed: sub-index, directory README, and excluded skill accepted"
echo "unindexed: docs/orphan.md reported despite URL, code-span and fence links"
echo "untracked: ignored; linked from sub-index: accepted"
echo "not links: comments, indented code (after blanks, headings, fences, in quotes), quoted fences, escaped, unused or paragraph-interrupting references"
echo "links: list continuations, used and consecutive references, escaped backslashes, comment openers in code, angle and parenthesised paths"
echo "multiline inlines: links accepted; code ignored with exact backtick runs and block boundaries"
echo "exclusions: deeper files under excluded directories are reported"
echo "workflow: docs.yml runs check-docs-index.py"
