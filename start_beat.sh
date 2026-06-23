#!/bin/bash
# Celery beat scheduler start script
#
# Usage:
#   ./start_beat.sh
#
# Environment variables:
#   REDIS_HOST     - Redis host (default: localhost)
#   REDIS_PORT     - Redis port (default: 6379)
#   LOG_LEVEL      - Log level (default: INFO)

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configuration
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

# Create and activate virtual environment
if [ ! -d "$PROJECT_ROOT/asphalt_venv" ]; then
    echo "Creating virtual environment (asphalt_venv)..."
    python3 -m venv "$PROJECT_ROOT/asphalt_venv"
fi
source "$PROJECT_ROOT/asphalt_venv/bin/activate"

# Set Python path (src for application code, packages for road_advisor_* packages)
export PYTHONPATH="${PROJECT_ROOT}/src:${PROJECT_ROOT}/packages:$PYTHONPATH"

# Export Redis settings
export CELERY_BROKER_URL="redis://${REDIS_HOST}:${REDIS_PORT}/0"
export CELERY_RESULT_BACKEND="redis://${REDIS_HOST}:${REDIS_PORT}/1"

cd "$PROJECT_ROOT"

echo "Starting Celery beat scheduler..."
python3 -m celery -A orchestrator.celery_app:celery_app beat \
    --loglevel="$LOG_LEVEL" \
    --scheduler=celery.beat:PersistentScheduler \
    --schedule="${PROJECT_ROOT}/celerybeat-schedule"
