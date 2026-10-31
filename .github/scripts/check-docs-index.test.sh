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

grep -F -q 'check-docs-index.py' "$workflow" \
  || fail "docs.yml does not run check-docs-index.py"

echo "PASS"
echo "indexed: sub-index, directory README, and excluded skill accepted"
echo "unindexed: docs/orphan.md reported despite URL, code-span and fence links"
echo "untracked: ignored; linked from sub-index: accepted"
echo "workflow: docs.yml runs check-docs-index.py"
