#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FEDSHOP_DIR="${ROOT_DIR}/reference-repos/FedShop"
DEFAULT_CONFIG="experiments/bsbm/snakefile/config.yaml"
SMOKE_CONFIG="experiments/bsbm/snakefile/config_small.yaml"
UV_REQUIREMENTS="${FEDSHOP_UV_REQUIREMENTS:-${ROOT_DIR}/scripts/fedshop-uv-requirements.txt}"
UV_PYTHON_VERSION="${FEDSHOP_PYTHON_VERSION:-3.8}"

export UV_CACHE_DIR="${UV_CACHE_DIR:-${ROOT_DIR}/.uv-cache}"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-${ROOT_DIR}/.uv-python}"

declare -a UV_BENCHMARK=(
  uv run
  --no-project
  --python "${UV_PYTHON_VERSION}"
  --with-requirements "${UV_REQUIREMENTS}"
  --script fedshop/benchmark.py
)

usage() {
  cat <<EOF
Usage: $0 COMMAND [options]

Commands:
  generate-data       Generate FedShop data.
  generate-queries    Generate query instances and RSA/reference results.
  evaluate            Evaluate configured query engines.
  full                Run generate-data, generate-queries, then evaluate.
  smoke               Dry-run a narrow q01/batch0 FedX execution.
  touch               Mark generation and evaluation outputs complete.

Options:
  --config PATH       FedShop config path relative to reference-repos/FedShop.
  --cores N           Snakemake cores, default: 1. Use -1 for all.
  --engine LIST       Comma-separated engine ids for evaluate.
  --query LIST        Comma-separated query ids, e.g. q01,q02.
  --instance LIST     Comma-separated instance ids.
  --batch LIST        Comma-separated batch ids.
  --attempt LIST      Comma-separated attempt ids.
  --clean LEVEL       Pass FedShop clean level to generate/evaluate.
  --dry-run           Ask Snakemake to plan without executing.
  --rerun-incomplete  Resume incomplete Snakemake jobs.

Environment:
  FEDSHOP_UV_REQUIREMENTS  Requirements file for uv, default: scripts/fedshop-uv-requirements.txt
  FEDSHOP_PYTHON_VERSION   Python version for uv, default: 3.8 from FedShop environment.yml
EOF
}

command="${1:-}"
if [[ -z "${command}" || "${command}" == "-h" || "${command}" == "--help" ]]; then
  usage
  exit 0
fi
shift

config="${DEFAULT_CONFIG}"
cores="1"
clean=""
dry_run="false"
rerun_incomplete="false"
declare -a filters=()

default_evaluation_filters() {
  if [[ "${#filters[@]}" -eq 0 ]]; then
    filters=(
      "engine=fedx,costfed,splendid,semagrow,anapsid,fedup_id,hibiscus,fedup,rsa"
      "query=q01,q02,q03,q04,q05,q06,q07,q08,q09,q10,q11,q12"
      "instance=0,1,2,3,4,5,6,7,8,9"
      "batch=0,1,2,3,4,5,6,7,8,9"
      "attempt=0,1,2"
    )
  fi
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --config)
      config="$2"
      shift 2
      ;;
    --cores)
      cores="$2"
      shift 2
      ;;
    --engine|--query|--instance|--batch|--attempt)
      key="${1#--}"
      filters+=("${key}=$2")
      shift 2
      ;;
    --clean)
      clean="$2"
      shift 2
      ;;
    --dry-run)
      dry_run="true"
      shift
      ;;
    --rerun-incomplete)
      rerun_incomplete="true"
      shift
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

run_benchmark() {
  local -a args=("$@")

  if ! command -v uv >/dev/null 2>&1; then
    echo "FedShop wrapper requires uv in PATH." >&2
    exit 127
  fi

  if [[ "${#filters[@]}" -gt 0 ]]; then
    args+=(--config "${filters[*]}")
  fi
  if [[ -n "${clean}" ]]; then
    args+=(--clean "${clean}")
  fi
  if [[ "${dry_run}" == "true" ]]; then
    args+=(--dry-run)
  fi
  if [[ "${rerun_incomplete}" == "true" ]]; then
    args+=(--rerun-incomplete)
  fi

  (cd "${FEDSHOP_DIR}" && "${UV_BENCHMARK[@]}" "${args[@]}")
}

case "${command}" in
  generate-data)
    run_benchmark generate data "${config}" --cores "${cores}"
    ;;
  generate-queries)
    run_benchmark generate queries "${config}" --cores "${cores}"
    ;;
  evaluate)
    default_evaluation_filters
    run_benchmark evaluate "${config}" --cores "${cores}"
    ;;
  full)
    run_benchmark generate data "${config}" --cores "${cores}"
    run_benchmark generate queries "${config}" --cores "${cores}"
    default_evaluation_filters
    run_benchmark evaluate "${config}" --cores "${cores}"
    ;;
  smoke)
    config="${SMOKE_CONFIG}"
    filters=("engine=fedx" "query=q01" "instance=0" "batch=0" "attempt=0")
    dry_run="true"
    run_benchmark evaluate "${config}" --cores "${cores}"
    ;;
  touch)
    if ! command -v uv >/dev/null 2>&1; then
      echo "FedShop wrapper requires uv in PATH." >&2
      exit 127
    fi
    (cd "${FEDSHOP_DIR}" && "${UV_BENCHMARK[@]}" generate data "${config}" --touch)
    (cd "${FEDSHOP_DIR}" && "${UV_BENCHMARK[@]}" generate queries "${config}" --touch)
    (cd "${FEDSHOP_DIR}" && "${UV_BENCHMARK[@]}" evaluate "${config}" --touch)
    ;;
  *)
    echo "Unknown command: ${command}" >&2
    usage
    exit 2
    ;;
esac
