#!/usr/bin/env sh
# Space entrypoint: start Ollama, load the model into memory, then serve the app.
set -eu

ollama serve >/tmp/ollama.log 2>&1 &
for i in $(seq 1 60); do
  curl -fsS http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break
  sleep 1
done

# Warm-up: load the model now so the first visitor does not wait for it
curl -fsS http://127.0.0.1:11434/api/generate \
  -d "{\"model\": \"$OLLAMA_MODEL\", \"prompt\": \"hi\", \"stream\": false, \"think\": false, \"options\": {\"num_predict\": 1}}" \
  >/dev/null 2>&1 || echo "warning: Ollama warm-up failed; see /tmp/ollama.log"

exec uvicorn app:app --host 0.0.0.0 --port "$PORT"
