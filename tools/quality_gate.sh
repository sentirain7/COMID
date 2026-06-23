#!/usr/bin/env bash
# Unified quality gate for local/CI validation.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${ROOT_DIR}/asphalt_venv/bin/python"

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "[ERROR] asphalt_venv is missing. Run ./start_all.sh --check first."
  exit 1
fi

MODE="${1:-quick}"
export PYTHONPATH="${ROOT_DIR}/src:${PYTHONPATH:-}"

run_quick() {
  echo "[STEP] ruff check"
  "${VENV_PYTHON}" -m ruff check .

  echo "[STEP] pytest collect-only"
  "${VENV_PYTHON}" -m pytest --collect-only -q

  echo "[STEP] frontend tests"
  (cd "${ROOT_DIR}/frontend" && npm test -- --run)
}

run_unit() {
  run_quick
  echo "[STEP] unit tests"
  "${VENV_PYTHON}" -m pytest tests/unit -q
}

case "${MODE}" in
  quick)
    run_quick
    ;;
  unit)
    run_unit
    ;;
  *)
    echo "Usage: $0 [quick|unit]"
    exit 2
    ;;
esac

echo "[OK] quality gate passed (${MODE})"
