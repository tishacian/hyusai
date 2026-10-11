#!/bin/sh
# Start Ollama, then pull the chat model and the embedder. Both stay in the
# same server so a local install does not add a second inference process.
set -eu

CHAT="${AGENTIUM_OLLAMA_CHAT_MODEL:-qwen3.5:4b}"
EMBED="${AGENTIUM_OLLAMA_EMBED_MODEL:-nomic-embed-text}"

ollama serve &
pid="$!"

i=0
until ollama list >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 60 ]; then
    printf 'ollama serve did not become ready\n' >&2
    exit 1
  fi
  sleep 1
done

ollama pull "$CHAT"
ollama pull "$EMBED"
wait "$pid"
