#!/usr/bin/env bash
# bootstrap-webapp.sh — sobe o webapp local do zero a partir de um clone limpo.
#
# Não pressupõe nenhuma preparação prévia: gera o dataset (se faltar),
# sobe o Virtuoso via Docker, ingere os batches 0 e 1, gera as consultas
# instanciadas, compila o frontend e finalmente sobe o servidor em
# 0.0.0.0:8000.
#
# Requisitos: uv, node/npm, docker (com o daemon acessível).
#
# Uso:
#   bash scripts/bootstrap-webapp.sh [--port 8000]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FEDSHOP_PY="$HERE/fedshop-py"
WEBAPP="$HERE/webapp"
CONFIG="inputs/config/config_small.yaml"
PORT="8000"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

log() { echo "══ $* ══"; }

for bin in uv node npm docker; do
  command -v "$bin" >/dev/null 2>&1 || { echo "Faltando '$bin' no PATH — instale antes de continuar." >&2; exit 1; }
done

cd "$FEDSHOP_PY"

if [[ -z "$(find data/dataset -maxdepth 1 -name '*.nq' -print -quit 2>/dev/null)" ]]; then
  log "gerando dataset (products + sources)"
  uv run fedshop generate products --config "$CONFIG"
  uv run fedshop generate sources --config "$CONFIG"
else
  log "dataset já existe em data/dataset/ — pulando geração"
fi

log "subindo Virtuoso"
docker compose -f docker/virtuoso.yml up -d
until curl -sf "http://localhost:8890/sparql?query=ASK%20%7B%3Fs%20%3Fp%20%3Fo%7D" >/dev/null; do
  sleep 2
done

for batch in 0 1; do
  mapping="data/virtuoso-proxy-mapping-batch${batch}.json"
  if [[ -f "$mapping" ]]; then
    log "batch $batch já ingerido ($mapping existe) — pulando"
  else
    log "ingerindo batch $batch"
    uv run fedshop ingest batch "$batch" --config "$CONFIG"
  fi
done

if [[ ! -f benchmark/generation/q01/instance_0/injected.sparql ]]; then
  log "gerando consultas instanciadas (batch 0)"
  uv run fedshop query run-all --config "$CONFIG" --bench-dir benchmark --batch-id 0
else
  log "consultas instanciadas já existem — pulando"
fi

if [[ ! -d "$WEBAPP/frontend/dist" ]]; then
  log "compilando frontend"
  (cd "$WEBAPP/frontend" && npm install && npm run build)
else
  log "frontend já compilado — pulando"
fi

cd "$WEBAPP"
log "subindo webapp em http://0.0.0.0:${PORT}/"
uv run uvicorn app:app --host 0.0.0.0 --port "$PORT"
