#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# SENTINEL-CI — unified post-deploy QA gate (readiness 100 %)
#
# Runs smoke probe, resolver, deck resolve, Playwright S1+S2 and S3 harnesses.
# Exits non-zero if any step fails the 100 % threshold.
#
# Usage:
#   ./scripts/qa_demo_gate.sh                    # gate only (no workspace reset)
#   ./scripts/qa_demo_gate.sh --with-reset       # step 0: predemo_reset.sh then gate
#   ./scripts/qa_demo_gate.sh --skip-playwright  # API/resolver only (fast)
#
# Environment (same as predemo_reset / smoke probe):
#   AGENTIUM_HOST, AGENTIUM_EMAIL, AGENTIUM_PASSWORD, WORKSPACE_SLUG
#   QA_GATE_DATE=YYYY-MM-DD  (default: today, Africa/Abidjan)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WITH_RESET=0
SKIP_PLAYWRIGHT=0
for arg in "$@"; do
  case "$arg" in
    --with-reset) WITH_RESET=1 ;;
    --skip-playwright) SKIP_PLAYWRIGHT=1 ;;
    -h|--help)
      sed -n '2,14p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (try --help)" >&2
      exit 2
      ;;
  esac
done

AGENTIUM_HOST="${AGENTIUM_HOST:-https://agentium.papai.ai}"
WORKSPACE_SLUG="${WORKSPACE_SLUG:-sentinel-ci}"
QA_GATE_DATE="${QA_GATE_DATE:-$(TZ=Africa/Abidjan date +%Y-%m-%d)}"
GATE_DIR="${QA_GATE_DIR:-docs/status-screenshots/${QA_GATE_DATE}-qa-gate}"
case "$GATE_DIR" in
  /*) ;;
  *) GATE_DIR="$ROOT/$GATE_DIR" ;;
esac
mkdir -p "$GATE_DIR"

say()  { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }
ok()   { printf "  \033[1;32m✓\033[0m %s\n" "$*"; }
fail() { printf "  \033[1;31m✗\033[0m %s\n" "$*"; }

GATE_STEPS=()
GATE_FAIL=0

record_step() {
  local name="$1" status="$2" detail="${3:-}"
  GATE_STEPS+=("$name|$status|$detail")
  if [[ "$status" != "PASS" ]]; then
    GATE_FAIL=1
  fi
}

# ─── Step 0 (optional): pre-demo workspace reset ─────────────────────────────
if [[ "$WITH_RESET" -eq 1 ]]; then
  say "Step 0 — predemo_reset.sh (workspace clean state)"
  if AGENTIUM_HOST="$AGENTIUM_HOST" WORKSPACE_SLUG="$WORKSPACE_SLUG" \
     AGENTIUM_EMAIL="${AGENTIUM_EMAIL:-}" AGENTIUM_PASSWORD="${AGENTIUM_PASSWORD:-}" \
     bash "$ROOT/scripts/predemo_reset.sh"; then
    record_step "predemo_reset" "PASS" "demo_time_context + calendar reseed"
    ok "predemo_reset completed"
  else
    record_step "predemo_reset" "FAIL" "script exited non-zero"
    fail "predemo_reset failed"
  fi
else
  say "Step 0 — predemo_reset (skipped; pass --with-reset to run <2h before Vice Premier Ministre)"
  record_step "predemo_reset" "SKIP" "use --with-reset before demo"
fi

# ─── Step 1: smoke probe prod (26/26) ────────────────────────────────────────
say "Step 1 — smoke_predeploy_probe.py (26/26)"
SMOKE_LOG="$GATE_DIR/smoke-probe.log"
if AGENTIUM_HOST="$AGENTIUM_HOST" WORKSPACE_SLUG="$WORKSPACE_SLUG" \
   AGENTIUM_EMAIL="${AGENTIUM_EMAIL:-}" AGENTIUM_PASSWORD="${AGENTIUM_PASSWORD:-}" \
   python3 "$ROOT/scripts/smoke_predeploy_probe.py" 2>&1 | tee "$SMOKE_LOG"; then
  SMOKE_EXIT=0
else
  SMOKE_EXIT=$?
fi
SMOKE_TOTAL=$(grep -E '^Total : [0-9]+/[0-9]+ PASS' "$SMOKE_LOG" | tail -1 | sed -E 's/.*Total : ([0-9]+)\/([0-9]+).*/\1 \2/' || echo "0 26")
SMOKE_PASS=$(echo "$SMOKE_TOTAL" | awk '{print $1}')
SMOKE_MAX=$(echo "$SMOKE_TOTAL" | awk '{print $2}')
if [[ "$SMOKE_PASS" -ge 26 && "$SMOKE_MAX" -ge 26 ]]; then
  record_step "smoke_probe" "PASS" "${SMOKE_PASS}/${SMOKE_MAX}"
  ok "smoke ${SMOKE_PASS}/${SMOKE_MAX}"
else
  record_step "smoke_probe" "FAIL" "${SMOKE_PASS}/${SMOKE_MAX} (need 26/26)"
  fail "smoke ${SMOKE_PASS}/${SMOKE_MAX} — need 26/26"
fi

# ─── Step 2: S3 resolver local (12/12) ───────────────────────────────────────
say "Step 2 — test_s3_resolver.py (12/12)"
RESOLVER_LOG="$GATE_DIR/s3-resolver.log"
if (cd "$ROOT/backend" && PYTHONPATH=. python3 ../scripts/test_s3_resolver.py) 2>&1 | tee "$RESOLVER_LOG"; then
  record_step "s3_resolver_local" "PASS" "12/12"
  ok "S3 resolver 12/12"
else
  RESOLVER_PASS=$(grep -E 'Result: [0-9]+/' "$RESOLVER_LOG" | tail -1 | sed -E 's/Result: ([0-9]+)\/.*/\1/' || echo 0)
  record_step "s3_resolver_local" "FAIL" "${RESOLVER_PASS}/12"
  fail "S3 resolver ${RESOLVER_PASS}/12"
fi

# ─── Step 3: deck phrases resolve (14/14 PASS, 0 PARTIAL) ──────────────────
say "Step 3 — qa_deck_phrases_resolve.py (14/14 PASS)"
DECK_OUT="$GATE_DIR/deck-phrases-resolve.json"
DECK_LOG="$GATE_DIR/deck-resolve.log"
if QA_OUT="$DECK_OUT" AGENTIUM_HOST="$AGENTIUM_HOST" WORKSPACE_SLUG="$WORKSPACE_SLUG" \
   AGENTIUM_EMAIL="${AGENTIUM_EMAIL:-}" AGENTIUM_PASSWORD="${AGENTIUM_PASSWORD:-}" \
   python3 "$ROOT/scripts/qa_deck_phrases_resolve.py" 2>&1 | tee "$DECK_LOG"; then
  DECK_EXIT=0
else
  DECK_EXIT=$?
fi
if [[ -f "$DECK_OUT" ]]; then
  DECK_SUM=$(python3 -c "import json; s=json.load(open('$DECK_OUT'))['summary']; print(f\"{s['pass']}/{s['total']} PASS partial={s['partial']} fail={s['fail']}\")")
  DECK_PARTIAL=$(python3 -c "import json; print(json.load(open('$DECK_OUT'))['summary']['partial'])")
  DECK_FAIL_N=$(python3 -c "import json; print(json.load(open('$DECK_OUT'))['summary']['fail'])")
  if [[ "$DECK_PARTIAL" -eq 0 && "$DECK_FAIL_N" -eq 0 ]]; then
    record_step "deck_phrases_resolve" "PASS" "$DECK_SUM"
    ok "deck resolve $DECK_SUM"
  else
    record_step "deck_phrases_resolve" "FAIL" "$DECK_SUM"
    fail "deck resolve $DECK_SUM (need 14/14 PASS, 0 PARTIAL)"
  fi
else
  record_step "deck_phrases_resolve" "FAIL" "no JSON output"
  fail "deck resolve — missing $DECK_OUT"
fi

CONSOLE_FAIL=0

if [[ "$SKIP_PLAYWRIGHT" -eq 0 ]]; then
  # ─── Step 4: Playwright S1+S2 ──────────────────────────────────────────────
  say "Step 4 — qa_trame_full.mjs (S1+S2, 0 FAIL, 0 PARTIAL)"
  TRAME_OUT="$GATE_DIR"
  TRAME_LOG="$GATE_DIR/qa-trame-full.log"
  if (cd "$ROOT/scripts/playwright" && \
      AGENTIUM_HOST="$AGENTIUM_HOST" WORKSPACE_SLUG="$WORKSPACE_SLUG" \
      AGENTIUM_EMAIL="${AGENTIUM_EMAIL:-}" AGENTIUM_PASSWORD="${AGENTIUM_PASSWORD:-}" \
      OUT_DIR="$TRAME_OUT" node qa_trame_full.mjs) 2>&1 | tee "$TRAME_LOG"; then
    TRAME_EXIT=0
  else
    TRAME_EXIT=$?
  fi
  if [[ -f "$TRAME_OUT/qa-results.json" ]]; then
    cp "$TRAME_OUT/qa-results.json" "$GATE_DIR/qa-trame-results.json"
    TRAME_STATS=$(python3 - <<PY
import json
d=json.load(open("$GATE_DIR/qa-trame-results.json"))
results=d.get("results",[])
p=sum(1 for r in results if r.get("status")=="PASS")
pa=sum(1 for r in results if r.get("status")=="PARTIAL")
f=sum(1 for r in results if r.get("status")=="FAIL")
print(f"{p}P {pa}Pa {f}F")
errs=d.get("consoleErrors",[])
bad500=sum(1 for e in errs if "500" in e)
badpe=sum(1 for e in errs if e.startswith("pageerror:"))
print(f"console500={bad500} pageerror={badpe}")
PY
)
    TRAME_LINE=$(echo "$TRAME_STATS" | head -1)
    CONSOLE_LINE=$(echo "$TRAME_STATS" | tail -1)
    TRAME_FAIL=$(echo "$TRAME_LINE" | grep -oE '[0-9]+F' | tr -d F || echo 0)
    TRAME_PARTIAL=$(echo "$TRAME_LINE" | grep -oE '[0-9]+Pa' | sed 's/Pa//' || echo 0)
    if [[ "$TRAME_FAIL" -eq 0 && "$TRAME_PARTIAL" -eq 0 ]]; then
      record_step "qa_trame_full" "PASS" "$TRAME_LINE"
      ok "trame full $TRAME_LINE"
    else
      record_step "qa_trame_full" "FAIL" "$TRAME_LINE"
      fail "trame full $TRAME_LINE (need 0 FAIL, 0 PARTIAL)"
    fi
    if echo "$CONSOLE_LINE" | grep -qE 'console500=[1-9]|pageerror=[1-9]'; then
      CONSOLE_FAIL=1
      record_step "console_trame" "FAIL" "$CONSOLE_LINE"
      fail "console errors in trame run: $CONSOLE_LINE"
    else
      record_step "console_trame" "PASS" "$CONSOLE_LINE"
    fi
  else
    record_step "qa_trame_full" "FAIL" "missing qa-results.json"
    fail "trame full — no JSON output"
  fi

  # ─── Step 5: Playwright S3 ─────────────────────────────────────────────────
  say "Step 5 — qa_s3_security.mjs (S3+V21, 0 FAIL)"
  S3_LOG="$GATE_DIR/qa-s3-security.log"
  if (cd "$ROOT/scripts/playwright" && \
      AGENTIUM_HOST="$AGENTIUM_HOST" WORKSPACE_SLUG="$WORKSPACE_SLUG" \
      AGENTIUM_EMAIL="${AGENTIUM_EMAIL:-}" AGENTIUM_PASSWORD="${AGENTIUM_PASSWORD:-}" \
      OUT_DIR="$GATE_DIR" node qa_s3_security.mjs) 2>&1 | tee "$S3_LOG"; then
    S3_EXIT=0
  else
    S3_EXIT=$?
  fi
  if [[ -f "$GATE_DIR/qa-s3-results.json" ]]; then
    S3_STATS=$(python3 - <<PY
import json
d=json.load(open("$GATE_DIR/qa-s3-results.json"))
print(f"{d.get('pass',0)}P {d.get('partial',0)}Pa {d.get('fail',0)}F")
errs=d.get("consoleErrors",[])
bad500=sum(1 for e in errs if "500" in e)
badpe=sum(1 for e in errs if e.startswith("pageerror:"))
print(f"console500={bad500} pageerror={badpe}")
PY
)
    S3_LINE=$(echo "$S3_STATS" | head -1)
    S3_CONSOLE=$(echo "$S3_STATS" | tail -1)
    S3_FAIL=$(echo "$S3_LINE" | grep -oE '[0-9]+F' | tr -d F || echo 0)
    if [[ "$S3_FAIL" -eq 0 ]]; then
      record_step "qa_s3_security" "PASS" "$S3_LINE"
      ok "S3 security $S3_LINE"
    else
      record_step "qa_s3_security" "FAIL" "$S3_LINE"
      fail "S3 security $S3_LINE (need 0 FAIL)"
    fi
    if echo "$S3_CONSOLE" | grep -qE 'console500=[1-9]|pageerror=[1-9]'; then
      CONSOLE_FAIL=1
      record_step "console_s3" "FAIL" "$S3_CONSOLE"
      fail "console errors in S3 run: $S3_CONSOLE"
    else
      record_step "console_s3" "PASS" "$S3_CONSOLE"
    fi
  else
    record_step "qa_s3_security" "FAIL" "missing qa-s3-results.json"
    fail "S3 security — no JSON output"
  fi
else
  say "Steps 4–5 — Playwright (skipped; --skip-playwright)"
  record_step "qa_trame_full" "SKIP" "--skip-playwright"
  record_step "qa_s3_security" "SKIP" "--skip-playwright"
fi

# ─── Write gate-summary.json ─────────────────────────────────────────────────
GATE_SUMMARY="$GATE_DIR/gate-summary.json"
GATE_FAIL_PY=$GATE_FAIL
CONSOLE_FAIL_PY=$CONSOLE_FAIL
python3 - <<PY
import json, os, time
steps = []
for raw in """$(printf '%s\n' "${GATE_STEPS[@]}")""".strip().split("\n"):
    if not raw: continue
    parts = raw.split("|", 2)
    steps.append({"name": parts[0], "status": parts[1], "detail": parts[2] if len(parts)>2 else ""})
gate_fail = $GATE_FAIL_PY
console_fail = $CONSOLE_FAIL_PY
readiness = gate_fail == 0 and console_fail == 0
summary = {
    "host": os.environ.get("AGENTIUM_HOST", "$AGENTIUM_HOST"),
    "workspace": os.environ.get("WORKSPACE_SLUG", "$WORKSPACE_SLUG"),
    "gate_date": "$QA_GATE_DATE",
    "run_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "with_reset": $WITH_RESET,
    "steps": steps,
    "readiness_100": readiness,
    "exit_code": 0 if readiness else 1,
}
with open("$GATE_SUMMARY", "w", encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=2)
print(json.dumps(summary, ensure_ascii=False, indent=2))
PY

say "Gate summary → $GATE_SUMMARY"
if [[ "$GATE_FAIL" -eq 0 && "$CONSOLE_FAIL" -eq 0 ]]; then
  ok "READINESS 100 % — all gate steps PASS"
  exit 0
else
  fail "Gate FAILED — see $GATE_SUMMARY"
  exit 1
fi
