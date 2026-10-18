#!/usr/bin/env bash
# Build workflows + credentials from .env and (re)import them into the local n8n container.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
CONTAINER="$(docker compose ps -q n8n)"
[ -n "$CONTAINER" ] || { echo "ERROR: n8n container is not running (docker compose up -d)"; exit 1; }

MAIN_IDS=(sdrWf1Intake0001 sdrWf2Enriched01 sdrWf3Actions001 sdrWf4Errors0001 sdrWf5Expansion1)
SUB_IDS=(sdrSubSlackApi01 sdrSubEnrich0001 sdrSubHsSync0001 sdrSubHsCall0001 sdrSubHsNote0001
         sdrSubLeadCard01 sdrSubExpStart01 sdrSubExpCard001 sdrSubDraft00001 sdrSubReportErr1)

python3 scripts/build.py

docker cp .build/credentials.json "$CONTAINER":/tmp/sdr_credentials.json
docker cp .build/workflows.json "$CONTAINER":/tmp/sdr_workflows.json
docker compose exec -T n8n n8n import:credentials --input=/tmp/sdr_credentials.json
docker compose exec -T n8n n8n import:workflow --input=/tmp/sdr_workflows.json
docker compose exec -T -u root n8n rm -f /tmp/sdr_credentials.json /tmp/sdr_workflows.json
rm -f .build/credentials.json

for id in "${SUB_IDS[@]}" "${MAIN_IDS[@]}"; do
  docker compose exec -T n8n n8n publish:workflow --id="$id" >/dev/null
done

# env_file changes need a recreate, not just a restart
docker compose up -d --force-recreate n8n
for _ in $(seq 1 45); do
  curl -sf "http://localhost:${N8N_HOST_PORT:-8088}/healthz" >/dev/null && break
  sleep 2
done
echo "Deployed. Editor: http://localhost:${N8N_HOST_PORT:-8088}"
