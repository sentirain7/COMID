#!/bin/bash
# Frontend development server start script
#
# Usage:
#   ./start_frontend.sh         # Development mode
#   ./start_frontend.sh build   # Build for production
#   ./start_frontend.sh preview # Preview production build
#
# Requirements:
#   - Node.js >= 18
#   - npm or yarn

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

cd "$FRONTEND_DIR"

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

COMMAND="${1:-dev}"

case "$COMMAND" in
    "dev")
        echo "Starting frontend development server..."
        echo "Open http://localhost:5173 in your browser"
        npm run dev
        ;;
    "build")
        echo "Building frontend for production..."
        npm run build
        echo "Build complete! Output in frontend/dist/"
        ;;
    "preview")
        echo "Previewing production build..."
        npm run preview
        ;;
    "install")
        echo "Installing dependencies..."
        npm install
        ;;
    *)
        echo "Usage: $0 {dev|build|preview|install}"
        exit 1
        ;;
esac
