#!/bin/bash
set -e

MODELS_DIR="$(cd "$(dirname "$0")/../models" && pwd)"

echo "=== VoxVault Model Downloader ==="
echo ""

echo "[1/2] Downloading Voxtral Mini Q4 GGUF model (2.51 GB)..."
if [ ! -f "$MODELS_DIR/voxtral-q4.gguf" ]; then
  curl -L --progress-bar -o "$MODELS_DIR/voxtral-q4.gguf" \
    "https://huggingface.co/TrevorJS/voxtral-mini-realtime-gguf/resolve/main/voxtral-q4.gguf"
  echo "  -> voxtral-q4.gguf downloaded."
else
  echo "  -> voxtral-q4.gguf already exists, skipping."
fi

echo ""
echo "[2/2] Downloading tekken.json tokenizer (14.9 MB)..."
if [ ! -f "$MODELS_DIR/tekken.json" ]; then
  curl -L --progress-bar -o "$MODELS_DIR/tekken.json" \
    "https://huggingface.co/TrevorJS/voxtral-mini-realtime-gguf/resolve/main/tekken.json"
  echo "  -> tekken.json downloaded."
else
  echo "  -> tekken.json already exists, skipping."
fi

echo ""
echo "=== Done. Models are in $MODELS_DIR ==="
ls -lh "$MODELS_DIR"/*.gguf "$MODELS_DIR"/*.json 2>/dev/null || true
