#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "$0")" && pwd)
script=$script_dir/contract-change-label.sh

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

expect() {
  local action=$1 event_label=$2 pr_labels=$3 want=$4
  local got
  got=$(bash "$script" "$action" "$event_label" "$pr_labels")
  if [[ $got != "$want" ]]; then
    fail "action=$action event_label=$event_label labels=[$pr_labels] got $got, want $want"
  fi
}

expect synchronize "" "contract-change" true
expect synchronize "" "bug,contract-change" true
expect synchronize "" "bug" false
expect synchronize "" "" false
expect opened "" "contract-change" true
# The labeled payload omits the label that was just added.
expect labeled contract-change "" true
expect labeled contract-change "bug" true
expect labeled something-else "contract-change" true
expect labeled something-else "" false
# The unlabeled payload can still list the label being removed.
expect unlabeled contract-change "contract-change" false
expect unlabeled contract-change "contract-change,bug" false
expect unlabeled something-else "contract-change" true
expect unlabeled something-else "" false

echo "contract-change label decision: ok"
