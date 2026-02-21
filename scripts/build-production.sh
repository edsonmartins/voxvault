#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "============================================"
echo "  VoxVault — Production Build"
echo "============================================"
echo ""

# --- Step 1: Build Python sidecar with PyInstaller ---
echo "[1/3] Building Python orchestrator sidecar..."

cd "$PROJECT_DIR/python-orchestrator"

# Ensure venv exists
if [ ! -d ".venv" ]; then
  echo "  Creating virtual environment..."
  python3.12 -m venv .venv
fi

source .venv/bin/activate

# Install PyInstaller if needed
pip install -q pyinstaller

# Build standalone binary
echo "  Running PyInstaller..."
pyinstaller \
  --name voxvault-orchestrator \
  --onefile \
  --noconfirm \
  --clean \
  --hidden-import aiosqlite \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.lifespan.on \
  --collect-submodules anthropic \
  --collect-submodules openai \
  main.py

SIDECAR_PATH="$PROJECT_DIR/python-orchestrator/dist/voxvault-orchestrator"
echo "  Sidecar built: $SIDECAR_PATH"

# --- Step 2: Copy sidecar to Tauri bundle resources ---
echo ""
echo "[2/3] Preparing Tauri bundle resources..."

RESOURCES_DIR="$PROJECT_DIR/rust-core/src-tauri/resources"
mkdir -p "$RESOURCES_DIR"
cp "$SIDECAR_PATH" "$RESOURCES_DIR/voxvault-orchestrator"
chmod +x "$RESOURCES_DIR/voxvault-orchestrator"
echo "  Sidecar copied to $RESOURCES_DIR"

# --- Step 3: Build Tauri app ---
echo ""
echo "[3/3] Building Tauri application (.dmg)..."

cd "$PROJECT_DIR/rust-core"
npm run build
cargo tauri build

echo ""
echo "============================================"
echo "  Build Complete!"
echo "============================================"
echo ""
echo "Output:"
echo "  DMG: $PROJECT_DIR/rust-core/src-tauri/target/release/bundle/dmg/"
echo ""
echo "To install, open the .dmg and drag VoxVault to Applications."
