#!/bin/bash
# Monitoring stack start script
#
# Usage:
#   ./start_monitoring.sh         # Start monitoring stack
#   ./start_monitoring.sh stop    # Stop monitoring stack
#   ./start_monitoring.sh restart # Restart monitoring stack
#   ./start_monitoring.sh logs    # View logs
#
# Access:
#   Prometheus: http://localhost:9090
#   Grafana:    http://localhost:3030 (admin/asphalt123)

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$PROJECT_ROOT"

COMMAND="${1:-up}"

case "$COMMAND" in
    "up"|"start")
        echo "Starting monitoring stack..."
        docker-compose -f docker-compose.monitoring.yml up -d
        echo ""
        echo "Monitoring stack started!"
        echo ""
        echo "Access points:"
        echo "  Prometheus: http://localhost:9090"
        echo "  Grafana:    http://localhost:3030"
        echo "    Username: admin"
        echo "    Password: asphalt123"
        echo ""
        echo "Ensure API server is running for metrics collection:"
        echo "  ./start_api.sh --reload"
        ;;
    "down"|"stop")
        echo "Stopping monitoring stack..."
        docker-compose -f docker-compose.monitoring.yml down
        echo "Monitoring stack stopped."
        ;;
    "restart")
        echo "Restarting monitoring stack..."
        docker-compose -f docker-compose.monitoring.yml restart
        echo "Monitoring stack restarted."
        ;;
    "logs")
        docker-compose -f docker-compose.monitoring.yml logs -f
        ;;
    "status")
        docker-compose -f docker-compose.monitoring.yml ps
        ;;
    *)
        echo "Usage: $0 {up|down|restart|logs|status}"
        exit 1
        ;;
esac
