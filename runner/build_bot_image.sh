#!/usr/bin/env bash
set -euo pipefail

# Script to build the bot runner Docker image.
# Usage: ./runner/build_bot_image.sh [tag]
# Default tag: gamearena-bot:latest

TAG=${1:-gamearena-bot:latest}
HERE=$(cd "$(dirname "$0")" && pwd)
DOCKERFILE="$HERE/bot.Dockerfile"

if [ ! -f "$DOCKERFILE" ]; then
  echo "Dockerfile not found: $DOCKERFILE"
  exit 1
fi

echo "Building bot image with tag: $TAG"
docker build -f "$DOCKERFILE" -t "$TAG" "$HERE"

echo "Built $TAG"

echo "To use this image in the runner, set environment variable: BOT_DOCKER_IMAGE=$TAG"

