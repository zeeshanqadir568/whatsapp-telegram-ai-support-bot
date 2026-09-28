#!/usr/bin/env sh
# Publish the committed HEAD of this repo to a Hugging Face Docker Space.
#
#   deploy/push_to_hf_space.sh <hf-username>/<space-name>
#
# Only git-tracked files are sent (never .env or local data). The Space needs a
# README with YAML front matter, so it gets one generated here; the GitHub
# README is left untouched. Git will ask for your HF username and an access
# token with write scope (huggingface.co/settings/tokens) the first time.
set -eu

SPACE="${1:?usage: deploy/push_to_hf_space.sh <hf-username>/<space-name>}"
ROOT="$(git rev-parse --show-toplevel)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git -C "$ROOT" archive HEAD | tar -x -C "$WORK"
rm -rf "$WORK/docs"   # screenshots/GIFs are not needed to run and bloat the Space

{
  cat <<'YAML'
---
title: AI Support Bot (RAG) - Live Demo
emoji: 💬
colorFrom: indigo
colorTo: green
sdk: docker
app_port: 8000
pinned: false
license: mit
short_description: RAG support bot that answers only from its knowledge base
---

YAML
  cat "$ROOT/README.md"
} > "$WORK/README.md"

cd "$WORK"
git init -q -b main
git add -A
git -c user.name="$(git -C "$ROOT" config user.name)" -c user.email="$(git -C "$ROOT" config user.email)" \
  commit -q -m "Deploy $(git -C "$ROOT" rev-parse --short HEAD)"
git push --force "https://huggingface.co/spaces/$SPACE" main
echo "Pushed. Build logs: https://huggingface.co/spaces/$SPACE?logs=build"
