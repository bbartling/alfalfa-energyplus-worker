#!/usr/bin/env bash
# Linux-first launcher for the optional unmodified Alfalfa stack.
# Usage: scripts/launch.sh [config|up]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
SHA="af3caee5036d6c6ac10558307d7fd31fe12857de"
DEST="$ROOT/_alfalfa_upstream"
MODE="${1:-up}"
mkdir -p "$ROOT/work"

if [[ ! -d "$DEST/.git" ]]; then
  git init "$DEST"
  git -C "$DEST" remote add origin https://github.com/NatLabRockies/alfalfa.git
fi
git -C "$DEST" fetch --depth 1 origin "$SHA"
git -C "$DEST" checkout --detach FETCH_HEAD

if [[ ! -f "$ROOT/.env" ]]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
fi
set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a
# Shell variables override the upstream checkout's .env. Do not edit that file:
# it is part of the pinned Alfalfa tree.

if [[ "$MODE" == "config" ]]; then
  docker compose -f compose.alfalfa.yaml config > "$ROOT/work/compose-config.yml"
  python3 - <<'PY'
from pathlib import Path
text = Path("work/compose-config.yml").read_text()
if "kubernetes.docker.internal" in text:
    raise SystemExit("S3 endpoint still uses the Docker Desktop hostname")
if "http://minio:9000" not in text:
    raise SystemExit("in-network MinIO endpoint missing from rendered config")
print("compose config ok")
PY
  exit 0
fi

docker compose -f compose.alfalfa.yaml pull web worker minio mc mongo redis
docker compose -f compose.alfalfa.yaml build telemetry
docker compose -f compose.alfalfa.yaml up -d --no-build
echo "Alfalfa is on the internal network only (no host ports)."
echo "Smoke: docker compose -f compose.alfalfa.yaml exec -T telemetry python examples/alfalfa_smoke.py"
