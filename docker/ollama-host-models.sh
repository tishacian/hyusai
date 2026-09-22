#!/bin/sh
# Pull the nominal local models into the macOS Ollama process.
# Run this on the Mac, before compose.agentium.local-mac.yml.
set -eu

if ! command -v ollama >/dev/null 2>&1; then
  echo "ollama is not on PATH. Install the macOS build, 0.34 or newer, outside Docker." >&2
  exit 1
fi

CHAT="${AGENTIUM_OLLAMA_CHAT_MODEL:-qwen2.5:3b}"
EMBED="${AGENTIUM_OLLAMA_EMBED_MODEL:-nomic-embed-text}"

ollama pull "$CHAT"
ollama pull "$EMBED"
