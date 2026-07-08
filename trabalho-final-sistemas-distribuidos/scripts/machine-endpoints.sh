#!/usr/bin/env bash
# machine-endpoints.sh — Topologia 2: máquina única que serve TODOS os
# endpoints (vendor* E ratingsite*) para a engine/cliente remota.
#
# Pré-requisito: o dataset do config usado (por padrão data-dist/dataset/*.nq,
# gerado pelo config_dist.yaml) já sincronizado nesta máquina. Este script sobe
# o Virtuoso local e carrega o dataset completo — a separação vendor/ratingsite
# é feita por URL de grafo, então um único Virtuoso atende os dois papéis.
#
# Uso:
#   bash scripts/machine-endpoints.sh [--config PATH]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FEDSHOP_PY="$HERE/fedshop-py"
CONFIG="inputs/config/config_dist.yaml"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

cd "$FEDSHOP_PY"

# Which compose file / port to use is read from the config itself
# (services.virtuoso_compose_file / virtuoso_port) — config_dist.yaml points
# at docker/virtuoso-dist.yml (port 8891), whose volume mounts data-dist/dataset.
# Using the wrong compose file here would silently load from an empty/wrong
# directory (docker/virtuoso.yml mounts inputs/product-dataset instead).
read -r COMPOSE_FILE VIRTUOSO_PORT <<< "$(uv run python -c "
from fedshop.config import load_config
v = load_config('$CONFIG').generation.virtuoso
print(v.compose_file, v.port)
")"

echo "══ Máquina ENDPOINTS (T2): subindo Virtuoso ($COMPOSE_FILE, porta $VIRTUOSO_PORT) ══"
docker compose -f "$COMPOSE_FILE" up -d

echo -n "  aguardando Virtuoso"
for _ in $(seq 1 30); do
  if curl -sf "http://localhost:${VIRTUOSO_PORT}/sparql?query=ASK+%7B+%3Fs+%3Fp+%3Fo+%7D" >/dev/null 2>&1; then
    echo " ok"; break
  fi
  echo -n "."; sleep 2
done

N_BATCH="$(uv run python -c "
from fedshop.config import load_config
print(load_config('$CONFIG').generation.n_batch)
")"

echo "══ Ingerindo $N_BATCH batch(es) (dataset completo) ══"
for ((b=0; b<N_BATCH; b++)); do
  echo "  batch $b"
  uv run fedshop ingest batch "$b" --config "$CONFIG"
done

IP="$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "Virtuoso pronto. Confirme o acesso pela rede a partir da máquina A:"
echo "  curl \"http://${IP:-IP_DESTA_MAQUINA}:${VIRTUOSO_PORT}/sparql?query=ASK%20%7B%3Fs%20%3Fp%20%3Fo%7D\""
echo
echo "Na máquina A, rode o benchmark T2 apontando os dois papéis para cá:"
echo "  bash scripts/run-topology-benchmark.sh --topology 2 \\"
echo "    --vendor-host ${IP:-IP_DESTA_MAQUINA} --ratingsite-host ${IP:-IP_DESTA_MAQUINA}"
