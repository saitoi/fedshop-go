#!/usr/bin/env bash
# run-benchmark.sh — full fedshop-py pipeline from generation to metrics.
#
# Run from fedshop-py/:
#   bash run-benchmark.sh
#
# Options:
#   --config PATH      config file (default: config/config_small.yaml)
#   --bench-dir PATH   evaluation output root (default: benchmark/)
#   --engine NAME      restrict evaluation to one engine (default: all)
#   --query NAME       restrict evaluation to one query, e.g. q01
#   --skip-docker      skip docker compose up/down (services already running)
#   --skip-generate    skip Phase 1 (data already generated)
#   --skip-ingest      skip Phase 2 (data already ingested)
#   --skip-queries     skip Phase 3 (queries already instantiated)
#   --skip-evaluate    skip Phase 4 (already evaluated)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

# ── Defaults ─────────────────────────────────────────────────────────────────
CONFIG="config/config_small.yaml"
BENCH_DIR="benchmark"
ENGINE_FILTER=""
QUERY_FILTER=""
SKIP_DOCKER=false
SKIP_GENERATE=false
SKIP_INGEST=false
SKIP_QUERIES=false
SKIP_EVALUATE=false

# ── Arg parsing ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)       CONFIG="$2";        shift 2 ;;
    --bench-dir)    BENCH_DIR="$2";     shift 2 ;;
    --engine)       ENGINE_FILTER="$2"; shift 2 ;;
    --query)        QUERY_FILTER="$2";  shift 2 ;;
    --skip-docker)  SKIP_DOCKER=true;   shift ;;
    --skip-generate) SKIP_GENERATE=true; shift ;;
    --skip-ingest)  SKIP_INGEST=true;   shift ;;
    --skip-queries) SKIP_QUERIES=true;  shift ;;
    --skip-evaluate) SKIP_EVALUATE=true; shift ;;
    -h|--help)
      sed -n '2,/^set /p' "$0" | grep '^#' | sed 's/^# \{0,2\}//'
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────
FEDSHOP="uv run fedshop --"
run() { echo "  $ $*"; "$@"; }

section() { echo; echo "══════════════════════════════════════════════════════"; echo "  $*"; echo "══════════════════════════════════════════════════════"; }

wait_http() {
  local url="$1" label="${2:-$1}"
  echo -n "  waiting for $label"
  for _ in $(seq 1 30); do
    if curl -sf "$url" >/dev/null 2>&1; then echo " ok"; return 0; fi
    echo -n "."; sleep 2
  done
  echo " TIMEOUT" >&2; return 1
}

# Read n_batch from config via Python (avoids duplicating resolver logic)
N_BATCH="$(uv run python -c "
from fedshop.config import load_config
print(load_config('$CONFIG').generation.n_batch)
")"

# ── Docker services ───────────────────────────────────────────────────────────
section "Docker: start Virtuoso + proxy"
if [[ "$SKIP_DOCKER" == true ]]; then
  echo "  skipped (--skip-docker)"
else
  run docker compose -f docker/virtuoso.yml up -d
  run docker compose -f docker/proxy.yml    up -d
  wait_http "http://localhost:8890/sparql?query=ASK+%7B+%3Fs+%3Fp+%3Fo+%7D" "Virtuoso :8890"
  wait_http "http://localhost:5555/get-stats" "proxy :5555"
fi

# ── Phase 1: generate ─────────────────────────────────────────────────────────
section "Phase 1: generate data"
if [[ "$SKIP_GENERATE" == true ]]; then
  echo "  skipped (--skip-generate)"
else
  run uv run fedshop generate products --config "$CONFIG"
  run uv run fedshop generate sources  --config "$CONFIG"
fi

# ── Phase 2: ingest (per batch) ───────────────────────────────────────────────
section "Phase 2: ingest batches 0..$((N_BATCH - 1))"
if [[ "$SKIP_INGEST" == true ]]; then
  echo "  skipped (--skip-ingest)"
else
  for batch in $(seq 0 $((N_BATCH - 1))); do
    run uv run fedshop ingest batch "$batch" --config "$CONFIG"
  done
fi

# ── Phase 3: query generation (per batch) ────────────────────────────────────
section "Phase 3: generate queries for batches 0..$((N_BATCH - 1))"
if [[ "$SKIP_QUERIES" == true ]]; then
  echo "  skipped (--skip-queries)"
else
  for batch in $(seq 0 $((N_BATCH - 1))); do
    run uv run fedshop query run-all \
      --config "$CONFIG" \
      --bench-dir "$BENCH_DIR" \
      --batch-id "$batch" \
      ${QUERY_FILTER:+--query-name "$QUERY_FILTER"}
  done
fi

# ── Phase 4: evaluate ─────────────────────────────────────────────────────────
section "Phase 4: evaluate engines"
if [[ "$SKIP_EVALUATE" == true ]]; then
  echo "  skipped (--skip-evaluate)"
else
  eval_args=(--config "$CONFIG" --bench-dir "$BENCH_DIR")
  [[ -n "$ENGINE_FILTER" ]] && eval_args+=(--engine "$ENGINE_FILTER")
  [[ -n "$QUERY_FILTER"  ]] && eval_args+=(--query  "$QUERY_FILTER")

  # Check prerequisites for each configured engine
  engines_in_config="$(uv run python -c "
from fedshop.config import load_config
print(' '.join(load_config('$CONFIG').evaluation.engines.keys()))
")"
  for eng in $engines_in_config; do
    [[ -n "$ENGINE_FILTER" && "$eng" != "$ENGINE_FILTER" ]] && continue
    run uv run fedshop evaluate prerequisites "$eng" --config "$CONFIG"
  done

  run uv run fedshop evaluate run-all "${eval_args[@]}"
fi

# ── Metrics ───────────────────────────────────────────────────────────────────
section "Metrics: compute"
METRICS_OUT="$BENCH_DIR/metrics.csv"
run uv run fedshop metrics compute "$METRICS_OUT" \
  --config "$CONFIG" \
  --bench-dir "$BENCH_DIR"
echo
echo "Done. Metrics written to $METRICS_OUT"
