#!/usr/bin/env bash
# start.sh - Quick start script for the Deal Command Center
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-web}"
PORT="${2:-5000}"

case "$MODE" in
    web)
        echo "Starting Deal Command Center web dashboard on port $PORT..."
        echo "Open http://localhost:$PORT in your browser."
        echo ""
        python run_web.py --port "$PORT"
        ;;
    cli)
        echo "Running Deal Command Center CLI..."
        python -m deal_command_center "${@:2}"
        ;;
    docker)
        echo "Starting with Docker Compose..."
        docker compose up --build -d
        echo ""
        echo "Dashboard running at http://localhost:5000"
        echo "Logs: docker compose logs -f"
        ;;
    stop)
        echo "Stopping Docker containers..."
        docker compose down
        ;;
    setup)
        echo "Installing dependencies..."
        pip install -r requirements.txt
        echo ""
        echo "Running credential setup..."
        python -m deal_command_center --setup
        ;;
    *)
        echo "Usage: ./start.sh [web|cli|docker|stop|setup] [port|cli-args]"
        echo ""
        echo "  web [port]   - Start web dashboard (default: port 5000)"
        echo "  cli [args]   - Run CLI tool with optional args"
        echo "  docker       - Start with Docker Compose"
        echo "  stop         - Stop Docker containers"
        echo "  setup        - Install deps and configure credentials"
        exit 1
        ;;
esac
