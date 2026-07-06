#!/usr/bin/env bash
# machine-webapp.sh — Máquina A: apresentação, webapp e motor de consulta.
#
# Aponta o webapp para os dois Virtuosos remotos (máquina B = vendor*,
# máquina C = ratingsite*) e desativa o gerenciamento local de infra/Docker,
# já que Virtuoso e proxy rodam nas outras máquinas.
#
# Pré-requisito: benchmark/generation/ e data/virtuoso-proxy-mapping-batch*.json
# já copiados para fedshop-py/ nesta máquina (gerados onde os dados foram
# preparados), e o frontend já compilado (webapp/frontend && npm run build).
#
# Uso:
#   bash scripts/machine-webapp.sh --vendor-host IP_B --ratingsite-host IP_C
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEBAPP="$HERE/webapp"

VENDOR_HOST=""
RATINGSITE_HOST=""
PORT="8000"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --vendor-host)     VENDOR_HOST="$2";     shift 2 ;;
    --ratingsite-host) RATINGSITE_HOST="$2"; shift 2 ;;
    --port)            PORT="$2";            shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$VENDOR_HOST" || -z "$RATINGSITE_HOST" ]]; then
  echo "Uso: $0 --vendor-host IP_B --ratingsite-host IP_C [--port 8000]" >&2
  exit 2
fi

if [[ ! -d "$WEBAPP/frontend/dist" ]]; then
  echo "Frontend não compilado — rodando 'npm install && npm run build' em webapp/frontend..."
  (cd "$WEBAPP/frontend" && npm install && npm run build)
fi

cd "$WEBAPP"

echo "══ Máquina WEBAPP: apontando para vendor=$VENDOR_HOST ratingsite=$RATINGSITE_HOST ══"
curl -sf "http://${VENDOR_HOST}:8890/sparql?query=ASK%20%7B%3Fs%20%3Fp%20%3Fo%7D" >/dev/null \
  && echo "  vendor endpoint ok" || echo "  aviso: vendor endpoint não respondeu (siga mesmo assim)"
curl -sf "http://${RATINGSITE_HOST}:8890/sparql?query=ASK%20%7B%3Fs%20%3Fp%20%3Fo%7D" >/dev/null \
  && echo "  ratingsite endpoint ok" || echo "  aviso: ratingsite endpoint não respondeu (siga mesmo assim)"

FEDSHOP_WEBAPP_MANAGE_INFRA=0 \
FEDSHOP_VENDOR_ENDPOINT="http://${VENDOR_HOST}:8890/sparql" \
FEDSHOP_RATINGSITE_ENDPOINT="http://${RATINGSITE_HOST}:8890/sparql" \
uv run uvicorn app:app --host 0.0.0.0 --port "$PORT"
