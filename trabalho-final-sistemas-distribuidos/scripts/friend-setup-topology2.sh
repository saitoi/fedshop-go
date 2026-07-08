#!/usr/bin/env bash
# friend-setup-topology2.sh — Máquina B (topologia 2): do `git pull` até o
# Virtuoso pronto para servir os endpoints, sem tocar em nenhum Virtuoso já
# existente nesta máquina.
#
# Isolamento: usa docker/virtuoso-dist.yml (serviço "dist-virtuoso", porta
# 8891, volume próprio em data-dist/dataset) em vez de docker/virtuoso.yml —
# container, porta e dados completamente separados de qualquer Virtuoso que
# você já tenha rodando localmente (ex.: docker-bsbm-virtuoso-1 na 8890).
#
# Pré-requisito: o arquivo data-dist-dataset.zip (recebido de quem está
# rodando as topologias 1/3) na raiz do repo (trabalho-final-sistemas-distribuidos/)
# ou em um caminho passado via --zip.
#
# Uso:
#   bash scripts/friend-setup-topology2.sh [--zip PATH] [--branch NAME] [--skip-pull]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FEDSHOP_PY="$HERE/fedshop-py"
ZIP_PATH="$HERE/data-dist-dataset.zip"
BRANCH=""
SKIP_PULL=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --zip) ZIP_PATH="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --skip-pull) SKIP_PULL=true; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

command -v docker >/dev/null || { echo "ERRO: docker não encontrado no PATH." >&2; exit 1; }
command -v uv >/dev/null || { echo "ERRO: uv não encontrado no PATH (https://docs.astral.sh/uv/)." >&2; exit 1; }

echo "══ 1/5: git pull ══"
if [[ "$SKIP_PULL" == true ]]; then
  echo "  pulado (--skip-pull)"
else
  cd "$HERE"
  if [[ -n "$BRANCH" ]]; then
    git fetch origin "$BRANCH"
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
  else
    git pull
  fi
fi

echo "══ 2/5: instalando dependências (uv sync) ══"
cd "$FEDSHOP_PY"
uv sync

echo "══ 3/5: extraindo dataset (${ZIP_PATH}) ══"
if [[ ! -f "$ZIP_PATH" ]]; then
  echo "ERRO: não encontrei $ZIP_PATH — copie o zip recebido para lá ou passe --zip PATH." >&2
  exit 1
fi
mkdir -p "$FEDSHOP_PY/data-dist"
unzip -oq "$ZIP_PATH" -d "$FEDSHOP_PY"
n_nq="$(find "$FEDSHOP_PY/data-dist/dataset" -name '*.nq' | wc -l | tr -d ' ')"
echo "  ${n_nq} arquivos .nq extraídos em data-dist/dataset/"
if [[ "$n_nq" -lt 1 ]]; then
  echo "ERRO: nenhum .nq encontrado após extrair — verifique o zip." >&2
  exit 1
fi

echo "══ 4/5: subindo Virtuoso isolado + ingerindo os batches ══"
echo "  (container docker-dist-virtuoso-1, porta 8891 — não mexe em nenhum"
echo "   Virtuoso existente nesta máquina)"
cd "$HERE"
bash scripts/machine-endpoints.sh --config inputs/config/config_dist.yaml

echo
echo "══ 5/5: pronto ══"
echo "Envie o IP e a porta acima (8891) para quem vai rodar a topologia 2."
