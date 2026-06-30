#!/usr/bin/env bash
# deploy.sh — production deployment
#
# Usage: ./scripts/deploy.sh [IMAGE_TAG]
# Requires: docker, docker compose, .env present
set -euo pipefail

IMAGE_TAG="${1:-latest}"
COMPOSE="docker compose -f docker-compose.prod.yml"

echo "==> [1/5] Building image (tag: ${IMAGE_TAG})"
docker build --tag "brokerai:${IMAGE_TAG}" --tag "brokerai:latest" .

echo "==> [2/5] Pulling latest infra images"
$COMPOSE pull postgres redis minio nginx

echo "==> [3/5] Starting infra services"
$COMPOSE up -d postgres redis minio

echo "    Waiting for postgres..."
until docker compose -f docker-compose.prod.yml exec postgres pg_isready -U broker -d brokerai; do
  sleep 2
done

echo "==> [4/5] Running database migrations"
$COMPOSE run --rm migrate

echo "==> [5/5] Deploying application"
$COMPOSE up -d --no-deps api worker beat nginx

echo ""
echo "Done. Running containers:"
$COMPOSE ps
