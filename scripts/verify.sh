#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV_BIN="${NIKA_VENV_BIN:-/Users/user/Projects/nextloop/.venv/bin}"
if [[ -z "${BITS_BIN:-}" ]]; then
  if [[ -x "/Users/user/Desktop/Projects/bits-style/target/release/bits" ]]; then
    BITS_BIN="/Users/user/Desktop/Projects/bits-style/target/release/bits"
  else
    BITS_BIN="/Users/user/.cargo/bin/bits"
  fi
fi
export PYTHONPATH="$ROOT/src:/Users/user/Projects/nextloop/src${PYTHONPATH:+:$PYTHONPATH}"

echo "==> [1/5] bits style check"
"$BITS_BIN" style check src tests scripts/check_hygiene.py scripts/eval.py

echo "==> [2/5] ruff check"
"$VENV_BIN/ruff" check src tests scripts

echo "==> [3/5] mypy --strict"
"$VENV_BIN/mypy" src tests scripts

echo "==> [4/5] pytest"
"$VENV_BIN/pytest"

echo "==> [5/5] dead-code & hygiene check"
"$VENV_BIN/python" scripts/check_hygiene.py

echo "VERIFY_ALL_GREEN"
