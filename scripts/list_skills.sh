#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$HOME/.openclaw/workspace/skills}"
if [[ ! -d "$ROOT" ]]; then
  echo "No skills directory: $ROOT"
  exit 1
fi

printf "%-28s | %-7s\n" "skill" "status"
printf "%.0s-" {1..40}; echo

for d in "$ROOT"/*; do
  [[ -d "$d" ]] || continue
  name="$(basename "$d")"
  status="installed"
  [[ -f "$d/SKILL.md" ]] || status="missing-SKILL.md"
  printf "%-28s | %-7s\n" "$name" "$status"
done
