#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FEDSHOP_DIR="${ROOT_DIR}/reference-repos/FedShop"
SRC_DIR="${ROOT_DIR}/reference-repos/query-engines"

link_empty_target() {
  local target="$1"
  local source="$2"

  if [[ ! -d "${source}" ]]; then
    echo "Missing source: ${source}" >&2
    exit 1
  fi

  if [[ -L "${target}" ]]; then
    ln -sfn "${source}" "${target}"
    return
  fi

  if [[ -d "${target}" ]] && [[ -z "$(find "${target}" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    rmdir "${target}"
    ln -s "${source}" "${target}"
    return
  fi

  if [[ ! -e "${target}" ]]; then
    ln -s "${source}" "${target}"
    return
  fi

  echo "Refusing to replace non-empty target: ${target}" >&2
  echo "Move it aside manually if you want to relink it." >&2
  exit 1
}

link_empty_target "${FEDSHOP_DIR}/engines/CostFed" "${SRC_DIR}/CostFed"
link_empty_target "${FEDSHOP_DIR}/engines/SPLENDID" "${SRC_DIR}/splendid-server"
link_empty_target "${FEDSHOP_DIR}/engines/ANAPSID" "${SRC_DIR}/anapsid"
link_empty_target "${FEDSHOP_DIR}/engines/fedup" "${SRC_DIR}/fedup"
link_empty_target "${FEDSHOP_DIR}/engines/semagrow/semagrow" "${SRC_DIR}/semagrow"
link_empty_target "${FEDSHOP_DIR}/engines/semagrow/sevod-scraper" "${SRC_DIR}/sevod-scraper"
link_empty_target "${FEDSHOP_DIR}/generators/watdiv" "${SRC_DIR}/watdiv"
link_empty_target "${FEDSHOP_DIR}/fedshop/proxy/FedShop-proxy" "${SRC_DIR}/FedShop-proxy"

cat <<EOF
Linked updated source repositories into FedShop where the adapter paths are
structurally compatible.

FedX was not linked: FedShop's adapter expects a standalone org.example.FedX
wrapper jar, while current FedX is maintained inside Eclipse RDF4J at:
  ${SRC_DIR}/rdf4j-fedx

Port fedshop/engines/fedx.py before using current RDF4J FedX directly.
EOF
