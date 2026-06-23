#!/bin/bash
# Celery worker start script for Asphalt MD simulations
#
# Usage:
#   ./start_worker.sh                    # Start default worker
#   ./start_worker.sh screening          # Start screening queue worker
#   ./start_worker.sh confirm            # Start confirm queue worker
#   ./start_worker.sh layer              # Start layer queue worker
#   ./start_worker.sh all                # Start all queue workers
#
# Environment variables:
#   REDIS_HOST     - Redis host (default: localhost)
#   REDIS_PORT     - Redis port (default: 6379)
#   CONCURRENCY    - Number of concurrent workers (default: 4)
#   LOG_LEVEL      - Log level (default: INFO)

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configuration
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
CONCURRENCY="${CONCURRENCY:-4}"
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

QUEUE_ARG="$1"

case "$QUEUE_ARG" in
    "screening")
        echo "Starting Celery worker for screening queue..."
        python3 -m celery -A orchestrator.celery_app:celery_app worker \
            --queues=simulation.screening \
            --concurrency="$CONCURRENCY" \
            --loglevel="$LOG_LEVEL" \
            --hostname="screening@%h"
        ;;
    "confirm")
        echo "Starting Celery worker for confirm queue..."
        python3 -m celery -A orchestrator.celery_app:celery_app worker \
            --queues=simulation.confirm \
            --concurrency=2 \
            --loglevel="$LOG_LEVEL" \
            --hostname="confirm@%h"
        ;;
    "viscosity")
        echo "Starting Celery worker for viscosity queue..."
        python3 -m celery -A orchestrator.celery_app:celery_app worker \
            --queues=simulation.viscosity \
            --concurrency=1 \
            --loglevel="$LOG_LEVEL" \
            --hostname="viscosity@%h"
        ;;
    "layer")
        echo "Starting Celery worker for layer queue..."
        python3 -m celery -A orchestrator.celery_app:celery_app worker \
            --queues=simulation.layer \
            --concurrency=1 \
            --loglevel="$LOG_LEVEL" \
            --hostname="layer@%h"
        ;;
    "metrics")
        echo "Starting Celery worker for metrics queue..."
        python3 -m celery -A orchestrator.celery_app:celery_app worker \
            --queues=metrics \
            --concurrency="$CONCURRENCY" \
            --loglevel="$LOG_LEVEL" \
            --hostname="metrics@%h"
        ;;
    "priority")
        echo "Starting Celery worker for priority queue..."
        python3 -m celery -A orchestrator.celery_app:celery_app worker \
            --queues=priority \
            --concurrency=2 \
            --loglevel="$LOG_LEVEL" \
            --hostname="priority@%h"
        ;;
    "all")
        echo "Starting Celery worker for all queues..."
        python3 -m celery -A orchestrator.celery_app:celery_app worker \
            --queues=default,simulation,simulation.screening,simulation.confirm,simulation.viscosity,simulation.layer,simulation.gpu,metrics,priority \
            --concurrency="$CONCURRENCY" \
            --loglevel="$LOG_LEVEL" \
            --hostname="all@%h"
        ;;
    *)
        echo "Starting Celery worker for default and simulation queues..."
        python3 -m celery -A orchestrator.celery_app:celery_app worker \
            --queues=default,simulation,simulation.gpu \
            --concurrency="$CONCURRENCY" \
            --loglevel="$LOG_LEVEL" \
            --hostname="default@%h"
        ;;
esac
