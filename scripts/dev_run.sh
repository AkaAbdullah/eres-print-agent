#!/usr/bin/env bash
#
# Convenience wrapper for running the agent locally against print-hub's dev
# harness (print-hub/dev/mock-web.ts + a real print-hub) — see
# print-hub/README.md for starting those two first.
#
# Usage:
#   ./scripts/dev_run.sh pair MOCK-CODE   # first time only
#   ./scripts/dev_run.sh run

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ ! -d .venv ]; then
  echo "Creating .venv..."
  python3 -m venv .venv
  ./.venv/bin/pip install -e ".[dev]" -q
fi

export ERES_PRINT_AGENT_FORCE_MOCK_PRINTER="${ERES_PRINT_AGENT_FORCE_MOCK_PRINTER:-1}"
export ERES_PRINT_AGENT_ALLOW_INSECURE_HTTP="${ERES_PRINT_AGENT_ALLOW_INSECURE_HTTP:-1}"

if [ "${1:-}" = "pair" ]; then
  shift
  ./.venv/bin/eres-print-agent pair "$@" --web-url "${DEV_WEB_URL:-http://localhost:3101}"
else
  exec ./.venv/bin/eres-print-agent "$@"
fi
