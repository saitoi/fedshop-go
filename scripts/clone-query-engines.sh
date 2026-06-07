#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="${ROOT_DIR}/reference-repos/query-engines"

mkdir -p "${DEST_DIR}"

clone_or_update() {
  local name="$1"
  local url="$2"
  local path="${DEST_DIR}/${name}"

  if [[ -d "${path}/.git" ]]; then
    echo "Updating ${name}"
    git -C "${path}" fetch --depth 1 origin
    git -C "${path}" pull --ff-only
  else
    echo "Cloning ${name}"
    git clone --depth 1 "${url}" "${path}"
  fi
}

# Current/upstream source references for engines used by FedShop.
# FedX is maintained inside Eclipse RDF4J, not as the standalone wrapper that
# FedShop's fedx.py currently expects.
clone_or_update "rdf4j-fedx" "https://github.com/eclipse-rdf4j/rdf4j.git"
clone_or_update "CostFed" "https://github.com/AKSW/CostFed.git"
clone_or_update "semagrow" "https://github.com/semagrow/semagrow.git"
clone_or_update "splendid-server" "https://github.com/semagrow/fork-splendid-server.git"
clone_or_update "anapsid" "https://github.com/anapsid/anapsid.git"
clone_or_update "fedup" "https://github.com/GDD-Nantes/fedup.git"

# FedShop support repositories used by generation/evaluation.
clone_or_update "sevod-scraper" "https://github.com/semagrow/sevod-scraper.git"
clone_or_update "watdiv" "https://github.com/mhoangvslev/watdiv.git"
clone_or_update "FedShop-proxy" "https://github.com/mhoangvslev/FedShop-proxy.git"

echo
echo "Source repositories are available under ${DEST_DIR}"
