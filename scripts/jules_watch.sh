#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi
if [[ -z "${JULES_API_KEY:-}" ]]; then
  echo "JULES_API_KEY is missing (.env or env var)"
  exit 1
fi
exec .venv/bin/python scripts/jules_watch.py "$@"
