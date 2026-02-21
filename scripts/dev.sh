#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== VoxVault Development Server ==="
echo ""

# Start Python orchestrator in background
echo "[1/2] Starting Python Orchestrator (port 8766)..."
cd "$PROJECT_DIR/python-orchestrator"
source .venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8766 --reload &
PYTHON_PID=$!
echo "  -> Python PID: $PYTHON_PID"

# Cleanup on exit
cleanup() {
  echo ""
  echo "Shutting down..."
  kill $PYTHON_PID 2>/dev/null || true
  echo "Done."
}
trap cleanup EXIT INT TERM

# Start Tauri dev (includes Rust compilation + React dev server)
echo "[2/2] Starting Tauri Dev (Rust + React)..."
cd "$PROJECT_DIR/rust-core"
cargo tauri dev

# Wait for cleanup
wait
