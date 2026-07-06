#!/usr/bin/env bash
# machine-ratingsite.sh — Máquina C: Virtuoso que serve os grafos ratingsite*.
#
# Pré-requisito: fedshop-py/data/dataset/*.nq já sincronizado nesta máquina
# (copiado da máquina onde os dados foram gerados). Este script apenas sobe o
# Virtuoso local e carrega o dataset completo — o webapp filtra vendor*/ratingsite*
# por endpoint, então esta máquina recebe o mesmo dataset que a máquina B.
#
# Uso:
#   bash scripts/machine-ratingsite.sh [--config PATH]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FEDSHOP_PY="$HERE/fedshop-py"
CONFIG="inputs/config/config_small.yaml"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

cd "$FEDSHOP_PY"

echo "══ Máquina RATINGSITE: subindo Virtuoso ══"
docker compose -f docker/virtuoso.yml up -d

echo -n "  aguardando Virtuoso"
for _ in $(seq 1 30); do
  if curl -sf "http://localhost:8890/sparql?query=ASK+%7B+%3Fs+%3Fp+%3Fo+%7D" >/dev/null 2>&1; then
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
echo "  curl \"http://${IP:-IP_DESTA_MAQUINA}:8890/sparql?query=ASK%20%7B%3Fs%20%3Fp%20%3Fo%7D\""
echo
echo "Na máquina A, aponte FEDSHOP_RATINGSITE_ENDPOINT=http://${IP:-IP_DESTA_MAQUINA}:8890/sparql"
