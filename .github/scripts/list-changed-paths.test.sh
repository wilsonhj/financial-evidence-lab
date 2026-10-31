#!/usr/bin/env bash
set -euo pipefail

# Developer shells can export GIT_CONFIG_* with core.quotepath=false.
# Unset it so a dropped -z is judged against Git's default quoting, as on CI.
unset GIT_CONFIG_COUNT
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

script_dir=$(cd "$(dirname "$0")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
list_script=$script_dir/list-changed-paths.sh
workflow=$repo_root/.github/workflows/shared-paths.yml

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

repo=$(mktemp -d)
trap 'rm -rf "$repo"' EXIT

git -C "$repo" init -q -b main
git -C "$repo" config user.name "shared-path-test"
git -C "$repo" config user.email "shared-path-test@example.com"
git -C "$repo" config commit.gpgsign false
git -C "$repo" config diff.renames true

run_list() {
  (
    cd "$repo"
    bash "$list_script" "$1" "$2"
  )
}

mkdir -p "$repo/packages/contracts" "$repo/evals"
printf 'contract readme\n' > "$repo/packages/contracts/README.md"
git -C "$repo" add packages/contracts/README.md
git -C "$repo" commit -q -m "add contract readme"
rename_base=$(git -C "$repo" rev-parse HEAD)

git -C "$repo" mv packages/contracts/README.md evals/moved-readme.md
git -C "$repo" commit -q -m "move readme out of contracts"
rename_head=$(git -C "$repo" rev-parse HEAD)

rename_out=$(run_list "$rename_base" "$rename_head")
if ! grep -qx 'packages/contracts/README.md' <<< "$rename_out"; then
  fail "rename must still list packages/contracts/README.md. Output: $rename_out"
fi

plain=$(git -C "$repo" -c diff.renames=true diff --name-only "$rename_base" "$rename_head")
if grep -qx 'packages/contracts/README.md' <<< "$plain"; then
  fail "git diff --name-only without --no-renames listed packages/contracts/README.md, so the assertion would not depend on the flag. Output: $plain"
fi

mkdir -p "$repo/docs/decisions"
printf 'note\n' > "$repo/docs/decisions/$(printf 'caf\303\251.md')"
git -C "$repo" add -A -- docs/decisions
git -C "$repo" commit -q -m "add cafe decision"
cafe_head=$(git -C "$repo" rev-parse HEAD)

real_path=$(git -C "$repo" ls-files -z -- docs/decisions | tr '\0' '\n')
if [[ -z $real_path || $real_path == *$'\n'* ]]; then
  fail "expected one git path under docs/decisions, got: ${real_path-<empty>}"
fi
if ! LC_ALL=C grep -q '[^ -~]' <<< "$real_path"; then
  fail "git recorded an ASCII path ($real_path); the quoting check would not depend on -z"
fi

cafe_out=$(run_list "$rename_head" "$cafe_head")
if [[ $cafe_out != "$real_path" ]]; then
  fail "script output does not match the git path. script=[$cafe_out] git=[$real_path]"
fi
if ! grep -qE '^docs/decisions/' <<< "$cafe_out"; then
  fail "non-ASCII path does not match ^docs/decisions/: $cafe_out"
fi
case $cafe_out in
  \"*) fail "non-ASCII path has a leading double-quote: $cafe_out" ;;
  *\\*) fail "non-ASCII path contains a backslash escape: $cafe_out" ;;
esac

quoted=$(git -C "$repo" diff --name-only "$rename_head" "$cafe_head")
if [[ $quoted == "$cafe_out" ]]; then
  fail "git diff --name-only without -z did not differ from the raw path"
fi
case $quoted in
  \"*\\*) ;;
  *) fail "git diff --name-only without -z should C-quote the non-ASCII path, got: $quoted" ;;
esac

printf 'only\n' > "$repo/evals/only-change.txt"
git -C "$repo" add evals/only-change.txt
git -C "$repo" commit -q -m "evals only"
evals_head=$(git -C "$repo" rev-parse HEAD)

evals_out=$(run_list "$cafe_head" "$evals_head")
if ! grep -qx 'evals/only-change.txt' <<< "$evals_out"; then
  fail "evals-only change was not listed. Output: $evals_out"
fi

shared_prefix='^(\.github/|\.specify/|specs/|packages/contracts/|db/migrations/|docs/decisions/)'
if grep -E "$shared_prefix" <<< "$evals_out" >/dev/null; then
  fail "evals-only change matched the shared prefix. Output: $evals_out"
fi

if ! grep -F -q 'list-changed-paths.sh' "$workflow"; then
  fail "workflow does not contain list-changed-paths.sh, so production could inline a diff this test does not run"
fi
if ! grep -F -q 'contract-change-label.sh' "$workflow"; then
  fail "workflow does not contain contract-change-label.sh, so a labeled event can miss contract-change"
fi

echo "PASS"
echo "rename: packages/contracts/README.md stayed listed; git diff --name-only without --no-renames omitted it"
echo "non-ascii: listed the git path with no quoting; git diff --name-only without -z quoted it"
echo "evals: evals/only-change.txt listed and did not match the shared prefix"
echo "workflow: contains list-changed-paths.sh"
