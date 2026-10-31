#!/usr/bin/env bash
# Decide whether a pull_request event carries the contract-change label.
#
# Usage: contract-change-label.sh <action> <event-label> <comma-separated-pr-labels>
# Prints "true" or "false".
#
# On a `labeled` event, github.event.pull_request.labels is the set from before
# the label was applied, and the new name is github.event.label.name. On
# `unlabeled`, the array can still contain the label that is being removed.
# #360's shared-path check failed for that reason seven seconds after the
# label was added.
set -euo pipefail

action=${1:-}
event_label=${2:-}
pr_labels=${3:-}

has=false
if [[ -n $pr_labels ]]; then
  IFS=',' read -r -a names <<< "$pr_labels"
  for name in "${names[@]}"; do
    if [[ $name == "contract-change" ]]; then
      has=true
    fi
  done
fi

if [[ $action == "labeled" && $event_label == "contract-change" ]]; then
  has=true
fi
if [[ $action == "unlabeled" && $event_label == "contract-change" ]]; then
  has=false
fi

printf '%s\n' "$has"
