#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FEDSHOP_DIR="${ROOT_DIR}/reference-repos/FedShop"
IMAGE_NAME="${FEDSHOP_IMAGE:-fedshop-local}"

usage() {
  cat <<EOF
Usage: $0 build|shell|run [command...]

Commands:
  build        Build the FedShop Docker image from reference-repos/FedShop.
  shell        Open an interactive shell in the image with this workspace mounted.
  run CMD...   Run CMD in the image from /workspace/reference-repos/FedShop.

Environment:
  FEDSHOP_IMAGE  Image name, default: fedshop-local
EOF
}

case "${1:-}" in
  build)
    docker build -t "${IMAGE_NAME}" "${FEDSHOP_DIR}"
    ;;
  shell)
    docker run --rm -it --privileged \
      -v "${ROOT_DIR}:/workspace" \
      -w /workspace/reference-repos/FedShop \
      "${IMAGE_NAME}" bash
    ;;
  run)
    shift
    if [[ "$#" -eq 0 ]]; then
      echo "Missing command for run" >&2
      usage
      exit 2
    fi
    docker run --rm -it --privileged \
      -v "${ROOT_DIR}:/workspace" \
      -w /workspace/reference-repos/FedShop \
      "${IMAGE_NAME}" "$@"
    ;;
  *)
    usage
    exit 2
    ;;
esac
