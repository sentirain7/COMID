#!/bin/bash
# API server start script
#
# Usage:
#   ./start_api.sh              # Start API server
#   ./start_api.sh --reload     # Start with auto-reload (development)
#
# Environment variables:
#   API_HOST    - Host to bind (default: 0.0.0.0)
#   API_PORT    - Port to bind (default: 8000)

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configuration
API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8000}"

# Create and activate virtual environment
if [ ! -d "$PROJECT_ROOT/asphalt_venv" ]; then
    echo "Creating virtual environment (asphalt_venv)..."
    python3 -m venv "$PROJECT_ROOT/asphalt_venv"
fi
source "$PROJECT_ROOT/asphalt_venv/bin/activate"

# Set Python path (src for application code, packages for road_advisor_* packages)
export PYTHONPATH="${PROJECT_ROOT}/src:${PROJECT_ROOT}/packages:$PYTHONPATH"

cd "$PROJECT_ROOT"

RELOAD_FLAG=""
if [[ "$1" == "--reload" ]]; then
    RELOAD_FLAG="--reload"
    echo "Starting API server with auto-reload..."
else
    echo "Starting API server..."
fi

echo "API available at http://localhost:${API_PORT}"
echo "API docs at http://localhost:${API_PORT}/docs"

python3 -m uvicorn api.main:app \
    --host "$API_HOST" \
    --port "$API_PORT" \
    $RELOAD_FLAG
