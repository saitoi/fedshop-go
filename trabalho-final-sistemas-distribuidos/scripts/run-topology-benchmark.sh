#!/usr/bin/env bash
# run-topology-benchmark.sh — Máquina A (engine/cliente): roda o benchmark de
# uma topologia inteira e computa as métricas do diretório benchmark-dist/topoN.
#
# Topologias:
#   1  tudo nesta máquina (Virtuoso local; hosts padrão localhost)
#   2  todos endpoints em uma máquina remota (--vendor-host = --ratingsite-host)
#   3  vendors em uma máquina, ratingsites em outra
#
# Pré-requisitos (uma única vez, nesta máquina):
#   - dataset + consultas geradas:
#       uv run fedshop generate products --config inputs/config/config_dist.yaml
#       uv run fedshop generate sources  --config inputs/config/config_dist.yaml
#       (com Virtuoso local carregado) para cada lote B:
#       uv run fedshop query run-all --config inputs/config/config_dist.yaml \
#         --bench-dir benchmark-dist --batch-id B
#   - nas topologias 2/3, as máquinas remotas já rodando machine-endpoints.sh
#     (T2) ou machine-vendor.sh + machine-ratingsite.sh (T3).
#
# Uso:
#   bash scripts/run-topology-benchmark.sh --topology 1
#   bash scripts/run-topology-benchmark.sh --topology 2 --vendor-host IP_B --ratingsite-host IP_B
#   bash scripts/run-topology-benchmark.sh --topology 3 --vendor-host IP_B --ratingsite-host IP_C
#
# Opções:
#   --engines pyfedx,fedshop-go,rsa   motores a rodar (padrão: todos do config)
#   --query qNN                       restringe a uma consulta
#   --config PATH                     config (padrão inputs/config/config_dist.yaml)
#   --iperf                           mede banda no manifest (requer iperf3 -s remoto)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FEDSHOP_PY="$HERE/fedshop-py"
CONFIG="inputs/config/config_dist.yaml"
TOPOLOGY=""
VENDOR_HOST="localhost"
RATINGSITE_HOST="localhost"
ENGINES=""
QUERY=""
IPERF_FLAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --topology) TOPOLOGY="$2"; shift 2 ;;
    --vendor-host) VENDOR_HOST="$2"; shift 2 ;;
    --ratingsite-host) RATINGSITE_HOST="$2"; shift 2 ;;
    --engines) ENGINES="$2"; shift 2 ;;
    --query) QUERY="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    --iperf) IPERF_FLAG="--iperf"; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ "$TOPOLOGY" != "1" && "$TOPOLOGY" != "2" && "$TOPOLOGY" != "3" ]]; then
  echo "--topology deve ser 1, 2 ou 3" >&2; exit 2
fi
if [[ "$TOPOLOGY" != "1" && ( "$VENDOR_HOST" == "localhost" || "$RATINGSITE_HOST" == "localhost" ) ]]; then
  echo "topologias 2/3 exigem --vendor-host e --ratingsite-host remotos" >&2; exit 2
fi

TOPO_NAME="topo$TOPOLOGY"
BENCH_ROOT="$FEDSHOP_PY/benchmark-dist"
BENCH_DIR="$BENCH_ROOT/$TOPO_NAME"

cd "$FEDSHOP_PY"

read -r COMPOSE_FILE VIRTUOSO_PORT <<< "$(uv run python -c "
from fedshop.config import load_config
v = load_config('$CONFIG').generation.virtuoso
print(v.compose_file, v.port)
")"

echo "══ [$TOPO_NAME] proxy FedShop local (compatibilidade dos adaptadores) ══"
docker compose -f docker/proxy.yml up -d
for _ in $(seq 1 15); do
  curl -m 3 -sf http://localhost:5555/get-stats >/dev/null 2>&1 && break
  sleep 2
done

if [[ "$TOPOLOGY" == "1" ]]; then
  echo "══ [$TOPO_NAME] Virtuoso local ($COMPOSE_FILE, porta $VIRTUOSO_PORT) ══"
  docker compose -f "$COMPOSE_FILE" up -d
fi

echo "══ [$TOPO_NAME] reescrevendo mapping (vendor→$VENDOR_HOST, ratingsite→$RATINGSITE_HOST) ══"
uv run fedshop topology rewrite-mapping --config "$CONFIG" \
  --vendor-host "$VENDOR_HOST" --ratingsite-host "$RATINGSITE_HOST" --port "$VIRTUOSO_PORT"

echo "══ [$TOPO_NAME] verificando endpoints remotos ══"
for HOST in "$VENDOR_HOST" "$RATINGSITE_HOST"; do
  if ! curl -m 5 -sf "http://$HOST:${VIRTUOSO_PORT}/sparql?query=ASK+%7B+%3Fs+%3Fp+%3Fo+%7D" >/dev/null; then
    echo "ERRO: Virtuoso inacessível em http://$HOST:${VIRTUOSO_PORT}/sparql" >&2; exit 1
  fi
done

echo "══ [$TOPO_NAME] bench dir + manifest (RTT) ══"
uv run fedshop topology bootstrap "$TOPO_NAME" --bench-root "$BENCH_ROOT"
uv run fedshop topology manifest "$TOPO_NAME" --bench-dir "$BENCH_DIR" \
  --vendor-host "$VENDOR_HOST" --ratingsite-host "$RATINGSITE_HOST" $IPERF_FLAG

echo "══ [$TOPO_NAME] avaliação ══"
# O adaptador RSA lê estes hosts para montar as URLs de SERVICE remotas.
export FEDSHOP_VENDOR_HOST="$VENDOR_HOST"
export FEDSHOP_RATINGSITE_HOST="$RATINGSITE_HOST"
RUN_ARGS=(--config "$CONFIG" --bench-dir "$BENCH_DIR" --skip-existing-ok)
[[ -n "$QUERY" ]] && RUN_ARGS+=(--query "$QUERY")
if [[ -n "$ENGINES" ]]; then
  IFS=',' read -ra ENGINE_LIST <<< "$ENGINES"
  for ENGINE in "${ENGINE_LIST[@]}"; do
    echo "  ── engine: $ENGINE"
    uv run fedshop evaluate run-all "${RUN_ARGS[@]}" --engine "$ENGINE"
  done
else
  uv run fedshop evaluate run-all "${RUN_ARGS[@]}"
fi

echo "══ [$TOPO_NAME] métricas ══"
uv run fedshop metrics compute "$BENCH_DIR/metrics.csv" \
  --config "$CONFIG" --bench-dir "$BENCH_DIR"

echo
echo "Concluído: $BENCH_DIR/metrics.csv"
echo "Após rodar as 3 topologias, agregue com:"
echo "  uv run fedshop topology merge benchmark-dist/metrics_topology.csv"
echo "  uv run fedshop topology hypothesis benchmark-dist/hypothesis_topology.csv --from-csv benchmark-dist/metrics_topology.csv"
echo "  uv run fedshop topology typst-tables benchmark-dist/tables_topology.typ --from-csv benchmark-dist/metrics_topology.csv --hypothesis-csv benchmark-dist/hypothesis_topology.csv"
echo "  uv run fedshop topology plot benchmark-dist/plots --from-csv benchmark-dist/metrics_topology.csv"
