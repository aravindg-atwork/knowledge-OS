#!/bin/sh
set -e

ollama serve &
SERVE_PID=$!

until ollama list >/dev/null 2>&1; do
  echo "waiting for ollama to start..."
  sleep 1
done

echo "pulling ${LLM_MODEL:-llama3.2:1b}"
ollama pull "${LLM_MODEL:-llama3.2:1b}"

wait $SERVE_PID
