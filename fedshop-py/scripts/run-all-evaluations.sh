#!/usr/bin/env bash
# Run all configured engine evaluations and regenerate metrics/report tables.
#
# This script assumes data generation, Virtuoso ingestion, and query generation
# have already been completed for the selected bench directory. For a full
# generate->ingest->query->evaluate pipeline, use ../run-benchmark.sh.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

CONFIG="config/config_small.yaml"
BENCH_DIR="benchmark"
ENGINE_FILTER=""
QUERY_FILTER=""
SKIP_PREREQS=false
SKIP_EVALUATE=false
SKIP_METRICS=false
SKIP_EXISTING_OK=false

usage() {
  cat <<'EOF'
Run all configured engine evaluations and regenerate metrics/report tables.

This script assumes data generation, Virtuoso ingestion, and query generation
have already been completed for the selected bench directory. For a full
generate->ingest->query->evaluate pipeline, use ../run-benchmark.sh.

Usage:
  scripts/run-all-evaluations.sh [options]

Options:
  --config PATH       Config file (default: config/config_small.yaml)
  --bench-dir PATH    Benchmark directory (default: benchmark)
  --engine LIST       Comma-separated engine filter, e.g. fedshop-go,rsa
  --query qNN         Restrict evaluation to one query template
  --skip-prereqs      Do not compile/check engine prerequisites
  --skip-evaluate     Do not run engine evaluations, only metrics/reports
  --skip-existing-ok  Reuse existing numeric/timeout stats.csv files
  --skip-metrics      Do not recompute metrics/reports
  -h, --help          Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --bench-dir) BENCH_DIR="$2"; shift 2 ;;
    --engine) ENGINE_FILTER="$2"; shift 2 ;;
    --query) QUERY_FILTER="$2"; shift 2 ;;
    --skip-prereqs) SKIP_PREREQS=true; shift ;;
    --skip-evaluate) SKIP_EVALUATE=true; shift ;;
    --skip-existing-ok) SKIP_EXISTING_OK=true; shift ;;
    --skip-metrics) SKIP_METRICS=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

run() {
  echo "  $ $*"
  "$@"
}

section() {
  echo
  echo "══════════════════════════════════════════════════════"
  echo "  $*"
  echo "══════════════════════════════════════════════════════"
}

engine_java_home() {
  case "$1" in
    semagrow|splendid)
      echo "${JDK8_HOME:-/Library/Java/JavaVirtualMachines/temurin-8.jdk/Contents/Home}"
      ;;
    rsa)
      echo "${JDK_FEDUP_HOME:-/opt/homebrew/opt/openjdk}"
      ;;
    fedx|costfed)
      echo "${JDK17_HOME:-/opt/homebrew/opt/openjdk@17}"
      ;;
    *)
      echo ""
      ;;
  esac
}

configured_engines() {
  UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT/.uv-cache}" \
  UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$ROOT/.uv-python}" \
    uv run python - "$CONFIG" "$ENGINE_FILTER" <<'PY'
from __future__ import annotations

import sys
from fedshop.config import load_config

config_path, engine_filter = sys.argv[1], sys.argv[2]
engines = list(load_config(config_path).evaluation.engines.keys())
if engine_filter:
    requested = [item.strip() for item in engine_filter.split(",") if item.strip()]
    engines = [engine for engine in engines if engine in requested]
print(" ".join(engines))
PY
}

ENGINES="$(configured_engines)"
if [[ -z "$ENGINES" ]]; then
  echo "No engines selected." >&2
  exit 2
fi

COMMON_ENV=(
  "UV_CACHE_DIR=${UV_CACHE_DIR:-$ROOT/.uv-cache}"
  "UV_PYTHON_INSTALL_DIR=${UV_PYTHON_INSTALL_DIR:-$ROOT/.uv-python}"
)

section "Selected engines"
echo "  $ENGINES"

FAILED_PREREQS=()
if [[ "$SKIP_PREREQS" == false ]]; then
  section "Engine prerequisites"
  for engine in $ENGINES; do
    java_home="$(engine_java_home "$engine")"
    if [[ -n "$java_home" && -d "$java_home" ]]; then
      run env "${COMMON_ENV[@]}" JAVA_HOME="$java_home" PATH="$java_home/bin:$PATH" \
        uv run fedshop evaluate prerequisites "$engine" --config "$CONFIG" \
        || { echo "  WARNING: prerequisites for '$engine' failed — skipping evaluation." >&2; FAILED_PREREQS+=("$engine"); }
    else
      run env "${COMMON_ENV[@]}" \
        uv run fedshop evaluate prerequisites "$engine" --config "$CONFIG" \
        || { echo "  WARNING: prerequisites for '$engine' failed — skipping evaluation." >&2; FAILED_PREREQS+=("$engine"); }
    fi
  done
else
  section "Engine prerequisites"
  echo "  skipped (--skip-prereqs)"
fi

if [[ "$SKIP_EVALUATE" == false ]]; then
  section "Evaluate engines"
  eval_args=(--config "$CONFIG" --bench-dir "$BENCH_DIR")
  [[ -n "$QUERY_FILTER" ]] && eval_args+=(--query "$QUERY_FILTER")
  [[ "$SKIP_EXISTING_OK" == true ]] && eval_args+=(--skip-existing-ok)
  for engine in $ENGINES; do
    if [[ " ${FAILED_PREREQS[*]:-} " == *" $engine "* ]]; then
      echo "  Skipping $engine (prerequisites failed)."
      continue
    fi
    java_home="$(engine_java_home "$engine")"
    if [[ -n "$java_home" && -d "$java_home" ]]; then
      run env "${COMMON_ENV[@]}" JAVA_HOME="$java_home" PATH="$java_home/bin:$PATH" \
        uv run fedshop evaluate run-all "${eval_args[@]}" --engine "$engine"
    else
      run env "${COMMON_ENV[@]}" \
        uv run fedshop evaluate run-all "${eval_args[@]}" --engine "$engine"
    fi
  done
else
  section "Evaluate engines"
  echo "  skipped (--skip-evaluate)"
fi

if [[ "$SKIP_METRICS" == false ]]; then
  section "Metrics and tables"
  METRICS_OUT="$BENCH_DIR/metrics.csv"
  run env "${COMMON_ENV[@]}" uv run fedshop metrics compute "$METRICS_OUT" \
    --config "$CONFIG" \
    --bench-dir "$BENCH_DIR"
  run env "${COMMON_ENV[@]}" uv run fedshop metrics correctness \
    --from-csv "$METRICS_OUT" \
    --output "$BENCH_DIR/metrics_correctness.csv"
  run env "${COMMON_ENV[@]}" uv run fedshop metrics source-selection \
    --from-csv "$METRICS_OUT" \
    --output "$BENCH_DIR/metrics_source_selection.csv"
  run env "${COMMON_ENV[@]}" uv run fedshop metrics hypothesis-test \
    --from-csv "$METRICS_OUT" \
    --target-engine fedshop-go \
    --output "$BENCH_DIR/metrics_hypothesis.csv"
  run env "${COMMON_ENV[@]}" uv run fedshop metrics typst-tables \
    "$BENCH_DIR/typst-tables.typ" \
    --from-csv "$METRICS_OUT" \
    --hypothesis-csv "$BENCH_DIR/metrics_hypothesis.csv" \
    --attempt-policy all \
    --batch-id 1

  echo
  echo "Metrics written:"
  echo "  $METRICS_OUT"
  echo "  $BENCH_DIR/metrics_correctness.csv"
  echo "  $BENCH_DIR/metrics_source_selection.csv"
  echo "  $BENCH_DIR/typst-tables.typ"
  echo "  $BENCH_DIR/metrics_hypothesis.csv"
else
  section "Metrics and tables"
  echo "  skipped (--skip-metrics)"
fi
