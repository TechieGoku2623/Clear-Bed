#!/usr/bin/env bash
# Generate a Massachusetts Synthea population and export CSV only.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JAR="$ROOT/tools/synthea-with-dependencies.jar"
POP="${SYNTHEA_POPULATION:-5000}"
SEED="${SYNTHEA_SEED:-42}"
OUT="$ROOT/data/raw/synthea"
PROPS="$ROOT/tools/synthea.properties"

if [[ ! -f "$JAR" ]]; then
  echo "Missing $JAR. Run scripts/get_synthea.sh first." >&2
  exit 1
fi

if [[ -f "$OUT/csv/patients.csv" && "${FORCE_SYNTHEA:-0}" != "1" ]]; then
  echo "Synthea CSV already present at $OUT/csv (set FORCE_SYNTHEA=1 to regenerate)"
  exit 0
fi

mkdir -p "$OUT" "$ROOT/tools"
cat > "$PROPS" <<EOF
exporter.baseDirectory = ${OUT}
exporter.csv.export = true
exporter.fhir.export = false
exporter.fhir.use_us_core_ig = false
exporter.hospital.fhir.export = false
exporter.practitioner.fhir.export = false
exporter.metadata.export = false
exporter.ccda.export = false
exporter.text.export = false
generate.seed = ${SEED}
EOF

echo "Generating ${POP} Massachusetts patients (seed ${SEED}) into ${OUT}"
java -jar "$JAR" -c "$PROPS" -p "$POP" -s "$SEED" Massachusetts
echo "Synthea export:"
find "$OUT" -name '*.csv' | sort
