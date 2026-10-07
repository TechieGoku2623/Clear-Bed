#!/usr/bin/env bash
# Download the latest Synthea runnable jar into tools/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/tools/synthea-with-dependencies.jar"
mkdir -p "$ROOT/tools"

if [[ -f "$DEST" && "${FORCE_SYNTHEA_JAR:-0}" != "1" ]]; then
  echo "Synthea jar already present at $DEST"
  exit 0
fi

API="https://api.github.com/repos/synthetichealth/synthea/releases/latest"
URL="$(curl -fsSL "$API" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(a["browser_download_url"] for a in d["assets"] if a["name"]=="synthea-with-dependencies.jar"))')"
echo "Downloading $URL"
curl -fL --retry 3 -o "$DEST" "$URL"
echo "Saved $DEST"
