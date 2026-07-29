#!/usr/bin/env bash
# Refresh fire + rainfall data for the site. Safe to run from a git hook.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
echo "[rebuild] refreshing wildfire + rainfall data..."
"$PY" scripts/fetch_data.py

if [[ "${COMMIT_DATA:-0}" == "1" ]] && ! git diff --quiet -- data; then
  git add data/fires.geojson data/summary.json
  git commit -m "data: refresh wildfire + rainfall snapshot"
  echo "[rebuild] committed refreshed data"
fi

echo "[rebuild] done. Serve locally with: python3 -m http.server 8000"
