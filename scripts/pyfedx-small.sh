#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FEDSHOP_DIR="${ROOT_DIR}/reference-repos/FedShop"
CONFIG="experiments/bsbm/snakefile/config_small.yaml"
QUERY="q01"
INSTANCE="0"
BATCH="0"
CORES="1"
TIMEOUT="120"
OUT_DIR=""

export UV_CACHE_DIR="${UV_CACHE_DIR:-${ROOT_DIR}/.uv-cache}"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-${ROOT_DIR}/.uv-python}"
FEDSHOP_PYTHON_VERSION="${FEDSHOP_PYTHON_VERSION:-3.8}"
FEDSHOP_UV_REQUIREMENTS="${FEDSHOP_UV_REQUIREMENTS:-${ROOT_DIR}/scripts/fedshop-uv-requirements.txt}"

usage() {
  cat <<EOF
Usage: $0 COMMAND [options]

Commands:
  setup      Generate data, ingest Virtuoso Docker endpoints, and generate queries.
  run        Run one generated query with scripts/pyfedx.py.
  full       Run setup, then run.

Options:
  --config PATH       FedShop config relative to reference-repos/FedShop.
                      Default: experiments/bsbm/snakefile/config_small.yaml
  --query ID          Query id, default: q01.
  --instance ID       Query instance id, default: 0.
  --batch ID          Batch id, default: 0.
  --cores N           Snakemake cores, default: 1.
  --timeout SECONDS   pyfedx endpoint timeout, default: 120.
  --out-dir DIR       Output directory. Default:
                      reference-repos/FedShop/experiments/bsbm/benchmark/pyfedx/<query>/instance_<instance>/batch_<batch>

Examples:
  $0 full --query q01 --instance 0 --batch 0
  $0 run --query q01 --instance 0 --batch 0
EOF
}

need_uv() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required in PATH." >&2
    exit 127
  fi
}

need_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker is required in PATH." >&2
    exit 127
  fi
}

fedshop() {
  need_uv
  (
    cd "${FEDSHOP_DIR}"
    uv run \
      --no-project \
      --python "${FEDSHOP_PYTHON_VERSION}" \
      --with-requirements "${FEDSHOP_UV_REQUIREMENTS}" \
      --script fedshop/benchmark.py \
      "$@"
  )
}

pyfedx_python() {
  need_uv
  uv run --no-project --python "${FEDSHOP_PYTHON_VERSION}" python "$@"
}

setup_small() {
  need_docker
  fedshop generate data "${CONFIG}" --cores "${CORES}" --rerun-incomplete
  fedshop ingest "${CONFIG}" --cores "${CORES}" --config "batches=${BATCH}" --rerun-incomplete
  fedshop generate queries "${CONFIG}" --cores "${CORES}" --config "query=${QUERY} instance=${INSTANCE} batch=${BATCH}" --rerun-incomplete
}

make_pyfedx_config() {
  local mapping_file="${FEDSHOP_DIR}/experiments/bsbm/virtuoso-proxy-mapping-batch${BATCH}.json"
  local config_file="$1"
  if [[ ! -s "${mapping_file}" ]]; then
    echo "Missing ${mapping_file}; run '$0 setup --batch ${BATCH}' first." >&2
    exit 1
  fi
  mkdir -p "$(dirname "${config_file}")"
  pyfedx_python - "${mapping_file}" "${BATCH}" "${config_file}" <<'PY'
import json
import sys
from pathlib import Path

mapping_file, batch_s, outfile = sys.argv[1], sys.argv[2], sys.argv[3]
batch = int(batch_s)
mapping = json.loads(Path(mapping_file).read_text())

endpoints = {}
for vendor_id in range(10 * (batch + 1)):
    graph = f"http://www.vendor{vendor_id}.fr/"
    endpoints[graph] = mapping[graph]
for ratingsite_id in range(10 * (batch + 1)):
    graph = f"http://www.ratingsite{ratingsite_id}.fr/"
    endpoints[graph] = mapping[graph]

lines = [
    "@prefix sd: <http://www.w3.org/ns/sparql-service-description#> .",
    "@prefix fedx: <http://rdf4j.org/config/federation#> .",
    "",
]
for graph, endpoint in endpoints.items():
    lines.extend([
        f"<{graph}> a sd:Service ;",
        '    fedx:store "SPARQLEndpoint";',
        f'    sd:endpoint "{endpoint}";',
        "    fedx:supportsASKQueries true .",
        "",
    ])
Path(outfile).write_text("\n".join(lines), encoding="utf-8")
PY
}

run_pyfedx() {
  local generated_query="${FEDSHOP_DIR}/experiments/bsbm/benchmark/generation/${QUERY}/instance_${INSTANCE}/injected.sparql"
  if [[ ! -s "${generated_query}" ]]; then
    echo "Missing ${generated_query}; run '$0 setup --query ${QUERY} --instance ${INSTANCE}' first." >&2
    exit 1
  fi

  local resolved_out_dir="${OUT_DIR:-${FEDSHOP_DIR}/experiments/bsbm/benchmark/pyfedx/${QUERY}/instance_${INSTANCE}/batch_${BATCH}}"
  local pyfedx_config="${resolved_out_dir}/config_batch${BATCH}.ttl"
  make_pyfedx_config "${pyfedx_config}"

  mkdir -p "${resolved_out_dir}"
  pyfedx_python "${ROOT_DIR}/scripts/pyfedx.py" \
    --config "${pyfedx_config}" \
    --query "${generated_query}" \
    --out-result "${resolved_out_dir}/results.csv" \
    --out-source-selection "${resolved_out_dir}/source_selection.csv" \
    --query-plan "${resolved_out_dir}/query_plan.txt" \
    --stats "${resolved_out_dir}/stats.json" \
    --timeout "${TIMEOUT}"

  echo "results: ${resolved_out_dir}/results.csv"
  echo "source selection: ${resolved_out_dir}/source_selection.csv"
  echo "plan: ${resolved_out_dir}/query_plan.txt"
  echo "stats: ${resolved_out_dir}/stats.json"
}

command="${1:-}"
if [[ -z "${command}" || "${command}" == "-h" || "${command}" == "--help" ]]; then
  usage
  exit 0
fi
shift

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG="$2"
      shift 2
      ;;
    --query)
      QUERY="$2"
      shift 2
      ;;
    --instance)
      INSTANCE="$2"
      shift 2
      ;;
    --batch)
      BATCH="$2"
      shift 2
      ;;
    --cores)
      CORES="$2"
      shift 2
      ;;
    --timeout)
      TIMEOUT="$2"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

case "${command}" in
  setup)
    setup_small
    ;;
  run)
    run_pyfedx
    ;;
  full)
    setup_small
    run_pyfedx
    ;;
  *)
    echo "Unknown command: ${command}" >&2
    usage
    exit 2
    ;;
esac
