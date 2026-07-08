#!/usr/bin/env bash
# generate-topology-tables.sh — Aggregate whatever topo1/topo2/topo3 runs
# exist under benchmark-dist/ into metrics_topology.csv, hypothesis_topology.csv
# (if 2+ topologies are present) and tables_topology.typ.
#
# Safe to re-run at any point (e.g. while topo1 is still the only topology
# evaluated) — it just recomputes per-topology metrics.csv and merges
# whichever topo dirs it finds. Never touches fedshop-py/benchmark/ (the
# legacy, non-distributed results).
#
# Uso:
#   bash scripts/generate-topology-tables.sh [--config PATH] [--bench-root PATH]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FEDSHOP_PY="$HERE/fedshop-py"
CONFIG="inputs/config/config_dist.yaml"
BENCH_ROOT="benchmark-dist"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --bench-root) BENCH_ROOT="$2"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

cd "$FEDSHOP_PY"

TOPO_DIRS=()
for d in "$BENCH_ROOT"/topo1 "$BENCH_ROOT"/topo2 "$BENCH_ROOT"/topo3; do
  [[ -d "$d/evaluation" ]] && TOPO_DIRS+=("$d")
done

if [[ ${#TOPO_DIRS[@]} -eq 0 ]]; then
  echo "Nenhum diretório topoN/evaluation encontrado em $BENCH_ROOT" >&2
  exit 1
fi

echo "══ Topologias encontradas: ${TOPO_DIRS[*]} ══"

for d in "${TOPO_DIRS[@]}"; do
  echo "── metrics: $d ──"
  uv run fedshop metrics compute "$d/metrics.csv" --config "$CONFIG" --bench-dir "$d"
done

MERGED="$BENCH_ROOT/metrics_topology.csv"
echo "══ merge ══"
uv run fedshop topology merge "$MERGED" --bench-root "$BENCH_ROOT"

HYP_ARG=()
if [[ ${#TOPO_DIRS[@]} -ge 2 ]]; then
  HYP="$BENCH_ROOT/hypothesis_topology.csv"
  echo "══ hipóteses (HT1-HT5) ══"
  uv run fedshop topology hypothesis "$HYP" --from-csv "$MERGED"
  HYP_ARG=(--hypothesis-csv "$HYP")
else
  echo "Só 1 topologia disponível — pulando testes de hipótese (precisam de 2+)."
fi

TABLES="$BENCH_ROOT/tables_topology.typ"
echo "══ tabelas Typst ══"
uv run fedshop topology typst-tables "$TABLES" --from-csv "$MERGED" "${HYP_ARG[@]}"

PLOTS="$BENCH_ROOT/plots"
echo "══ plots ══"
uv run fedshop topology plot "$PLOTS" --from-csv "$MERGED"

echo
echo "Gerado:"
echo "  $MERGED"
[[ ${#TOPO_DIRS[@]} -ge 2 ]] && echo "  $BENCH_ROOT/hypothesis_topology.csv"
echo "  $TABLES"
echo "  $PLOTS/"
