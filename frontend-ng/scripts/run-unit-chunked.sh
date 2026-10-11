#!/usr/bin/env bash
# Run the unit suite in batches so each esbuild bundle set fits on a nearly
# full disk. Not a substitute for `npm run test:unit`: same specs, same runner,
# only the temp footprint differs.
set -uo pipefail
cd "$(dirname "$0")/.."

CHUNK="${CHUNK:-12}"
batches=$(mktemp)
trap 'rm -f "$batches"' EXIT

find src/app -name '*.spec.ts' | sort | awk -v n="$CHUNK" '
  { line = (NR % n == 1 || n == 1) ? $0 : line "," $0 }
  NR % n == 0 { print line; line = "" }
  END { if (line != "") print line }
' > "$batches"

total=$(find src/app -name '*.spec.ts' | wc -l | tr -d ' ')
count=$(wc -l < "$batches" | tr -d ' ')
pass=0
fail=0
bad=""

echo "chunked unit run: ${total} specs in ${count} batches of ${CHUNK}"

n=0
while IFS= read -r filter; do
  n=$((n + 1))
  specs=$(printf '%s' "$filter" | tr ',' '\n' | wc -l | tr -d ' ')
  out=$(FLOW_UNIT_FILTER="$filter" node scripts/run-unit.mjs 2>&1)
  status=$?
  p=$(printf '%s\n' "$out" | awk '/^# pass /{s+=$3} END{print s+0}')
  f=$(printf '%s\n' "$out" | awk '/^# fail /{s+=$3} END{print s+0}')
  pass=$((pass + p))
  fail=$((fail + f))
  printf 'batch %-2s  specs %-3s  pass %-5s fail %-3s exit %s\n' "$n" "$specs" "$p" "$f" "$status"
  if [ "$status" -ne 0 ] || [ "$f" -ne 0 ]; then
    bad="$bad $n"
    printf '%s\n' "$out" | grep -E '^(not ok|  error:|# fail|Error:)' | head -20
  fi
  rm -rf "${TMPDIR:-/tmp}"/flow-unit-* 2>/dev/null
done < "$batches"

echo "----------------------------------------"
echo "TOTAL pass=${pass} fail=${fail}"
if [ -n "$bad" ]; then
  echo "failed batches:${bad}"
  exit 1
fi
echo "all batches green"
