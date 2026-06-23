#!/bin/bash
# Test runner script for Asphalt MD project
#
# Usage:
#   ./run_tests.sh              # Run all tests
#   ./run_tests.sh e2e          # Run E2E tests only
#   ./run_tests.sh unit         # Run unit tests only
#   ./run_tests.sh integration  # Run integration tests only
#   ./run_tests.sh smoke        # Run smoke tests only
#   ./run_tests.sh coverage     # Run with coverage report

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Activate conda environment
CONDA_ENV_NAME="asphalt_env"
if [ -f "$HOME/miniforge3/bin/conda" ]; then
    eval "$($HOME/miniforge3/bin/conda shell.bash hook)"
fi
if ! conda env list 2>/dev/null | grep -q "^${CONDA_ENV_NAME} "; then
    echo "Creating conda environment from environment.yml..."
    conda env create -f "$PROJECT_ROOT/environment.yml"
fi
conda activate "$CONDA_ENV_NAME"

# Set Python path (src for application code, packages for road_advisor_* packages)
export PYTHONPATH="${PROJECT_ROOT}/src:${PROJECT_ROOT}/packages:$PYTHONPATH"

cd "$PROJECT_ROOT"

TEST_TYPE="${1:-all}"

case "$TEST_TYPE" in
    "e2e")
        echo "Running E2E tests..."
        python3 -m pytest tests/e2e/ -v
        ;;
    "unit")
        echo "Running unit tests..."
        python3 -m pytest tests/unit/ -v
        ;;
    "integration")
        echo "Running integration tests (mapped to e2e)..."
        python3 -m pytest tests/e2e/ -v
        ;;
    "smoke")
        echo "Running smoke tests..."
        python3 -m pytest tests/e2e/test_smoke.py -v
        ;;
    "coverage")
        echo "Running tests with coverage..."
        python3 -m pytest tests/ -v --cov=src --cov-report=html --cov-report=term-missing
        echo ""
        echo "Coverage report generated in htmlcov/"
        ;;
    "fast")
        echo "Running fast tests (excluding slow)..."
        python3 -m pytest tests/ -v -m "not slow"
        ;;
    *)
        echo "Running all tests..."
        python3 -m pytest tests/ -v
        ;;
esac
