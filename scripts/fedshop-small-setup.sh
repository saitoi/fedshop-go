#!/usr/bin/env bash
# fedshop-small-setup.sh
# Starts the official FedShop Docker image, applies all patches required to run
# config_small.yaml on Apple Silicon (arm64), and executes the three generation
# steps: generate-data → ingest → generate-queries.
#
# Results land in /tmp/experiments/bsbm/ on the host (mounted into the container).
#
# Usage (from repo root, on the host):
#   bash scripts/fedshop-small-setup.sh
set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────
CONTAINER=fedshop
IMAGE=minhhoangdang/fedshop:arm64
HOST_EXPERIMENTS=/tmp/experiments
FEDSHOP=/FedShop
CONFIG=experiments/bsbm/snakefile/config_small.yaml

# ── 1. Container ─────────────────────────────────────────────────────────────
echo "==> Starting container..."
docker rm -f "$CONTAINER" 2>/dev/null || true
docker run --detach --privileged --network host \
  --name "$CONTAINER" \
  --volume "${HOST_EXPERIMENTS}:${FEDSHOP}/experiments" \
  "$IMAGE"

# Wait for the inner Docker daemon to be ready
echo "==> Waiting for inner Docker daemon..."
until docker exec "$CONTAINER" docker info &>/dev/null 2>&1; do sleep 2; done

# Helper: run a shell command inside the container from /FedShop
inside() { docker exec "$CONTAINER" bash -c "cd ${FEDSHOP} && $*"; }

# ── 2. Git ───────────────────────────────────────────────────────────────────
echo "==> Updating FedShop repo to origin/main..."
# --recurse-submodules fails because engines/fedup is broken; skip it
inside "git fetch && git reset --hard origin/main"
# Init only the submodules needed for config_small (fedx, proxy, watdiv)
inside "git submodule update --init --force engines/FedX fedshop/proxy/FedShop-proxy generators/watdiv"

# ── 3. Docker compose plugin ─────────────────────────────────────────────────
# The image ships docker-compose as a standalone binary but the snakemake rules
# call "docker compose" (plugin syntax). Symlink to satisfy both.
echo "==> Installing docker compose plugin shim..."
inside "mkdir -p /usr/local/lib/docker/cli-plugins && \
        ln -sf /usr/bin/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose"

# ── 4. Patch config_small.yaml ───────────────────────────────────────────────
# config_small.yaml is an older file missing keys that the updated snakemake
# files (generate-queries.smk, ingest-data.smk) require. Add them all at once.
echo "==> Patching config_small.yaml..."
docker exec "$CONTAINER" python3 << 'PYEOF'
import numpy as np

CONFIG = '/FedShop/experiments/bsbm/snakefile/config_small.yaml'
cfg = open(CONFIG).read()

# 4a. Top-level use_docker key (generate-queries.smk:36, ingest-data.smk:35)
if 'use_docker:' not in cfg:
    cfg = 'use_docker: true\n' + cfg

# 4b. Virtuoso sub-keys (ingest-data.smk:43-48, generate-queries.smk:41)
virtuoso_block = (
    '    port: 8890\n'
    '    default_url: "http://localhost:${generation.virtuoso.port}"\n'
    '    default_endpoint: "${generation.virtuoso.default_url}/sparql"\n'
    '    isql: "/opt/virtuoso-opensource/bin/isql"\n'
    '    data_dir: "${generation.workdir}/model/dataset"\n'
)
if 'default_endpoint:' not in cfg:
    cfg = cfg.replace(
        '    service_name: "bsbm-virtuoso"\n',
        '    service_name: "bsbm-virtuoso"\n' + virtuoso_block,
    )

# 4c. federation_members / batch_members
# The resolver get_federation_members is only registered in
# experiments/bsbm/snakefile/omega_conf.py, which is NOT loaded when
# ingest-data.smk or generate-queries.smk run standalone. Compute and
# write the values statically.
if 'federation_members:' not in cfg:
    n_batch, n_v, n_r = 2, 20, 20
    _, ve = np.histogram(np.arange(n_v), n_batch); ve = ve[1:].astype(int) + 1
    _, re = np.histogram(np.arange(n_r), n_batch); re = re[1:].astype(int) + 1
    lines = ['    federation_members:']
    for b in range(n_batch):
        lines.append(f'      batch{b}:')
        for v in range(ve[b]):
            lines.append(f'        vendor{v}: "http://www.vendor{v}.fr/"')
        for r in range(re[b]):
            lines.append(f'        ratingsite{r}: "http://www.ratingsite{r}.fr/"')
    lines.append('    batch_members:')
    for b in range(n_batch):
        lines.append(f'      - "http://www.batch{b}.fr/"')
    block = '\n'.join(lines) + '\n'
    cfg = cfg.replace(
        '    data_dir: "${generation.workdir}/model/dataset"\n',
        '    data_dir: "${generation.workdir}/model/dataset"\n' + block,
    )

# 4d. Proxy host/port (generate-queries.smk:47)
if '    port: 5555' not in cfg:
    cfg = cfg.replace(
        '    service_name: "fedshop-proxy"\n',
        '    service_name: "fedshop-proxy"\n    host: "localhost"\n    port: 5555\n',
    )

open(CONFIG, 'w').write(cfg)
print('config_small.yaml patched')
PYEOF

# ── 5. Patch virtuoso.yml (memory) ───────────────────────────────────────────
# Default settings require ~8 GB free per instance; reduce for Docker Desktop.
echo "==> Reducing Virtuoso memory settings..."
VIRT_YML="${FEDSHOP}/experiments/bsbm/docker/virtuoso.yml"
docker exec "$CONTAINER" sed -i \
  -e 's/VIRT_Parameters_NumberOfBuffers: 680000/VIRT_Parameters_NumberOfBuffers: 170000/' \
  -e 's/VIRT_Parameters_MaxDirtyBuffers: 500000/VIRT_Parameters_MaxDirtyBuffers: 125000/' \
  -e 's/VIRT_Parameters_MaxQueryMem: 2G/VIRT_Parameters_MaxQueryMem: 512M/' \
  "$VIRT_YML"

# ── 6. Patch rdflib_algebra.py ───────────────────────────────────────────────
# Bug on origin/main: the SPARQL translator emits "SELECT WHERE DISTINCT ?vars {"
# instead of "SELECT DISTINCT ?vars {". Virtuoso rejects the malformed syntax.
# Fix: remove the misplaced WHERE so the output is "SELECT DISTINCT ?vars {".
echo "==> Patching rdflib_algebra.py (SELECT WHERE bug)..."
docker exec "$CONTAINER" sed -i \
  's/"-\*-SELECT-\*- WHERE " + "{"/"-*-SELECT-*- " + "{"/g' \
  "${FEDSHOP}/fedshop/algebra/rdflib_algebra.py"

# ── 7. Patch query.py ────────────────────────────────────────────────────────
echo "==> Patching query.py..."
docker exec "$CONTAINER" python3 << 'PYEOF'
f = '/FedShop/fedshop/query.py'
src = open(f).read()

# 7a. estimate_replacement_value_based_on_op raises ValueError for string values
# (e.g. product labels used with the "in" operator). Return strings as-is.
old_str = (
    '            else:\n'
    '                raise ValueError(f"Unsupported value type {type(value)} for value {value}!")'
)
new_str = (
    '            elif isinstance(value, str):\n'
    '                return value\n'
    '            else:\n'
    '                raise ValueError(f"Unsupported value type {type(value)} for value {value}!")'
)
if 'isinstance(value, str)' not in src:
    src = src.replace(old_str, new_str)

# 7b. execute_query raises RuntimeError when a query returns 0 rows. With the
# small dataset some instantiated queries genuinely have no matching data.
# Downgrade to a warning so the pipeline continues.
src = src.replace(
    'raise RuntimeError(f"{queryfile} returns no result...")',
    'logger.warning(f"{queryfile} returns no result, writing empty output")',
)

open(f, 'w').write(src)
print('query.py patched')
PYEOF

# ── 8. Run benchmark ─────────────────────────────────────────────────────────
echo "==> Step 1/3: generate data (~10 min)..."
inside "python fedshop/benchmark.py generate data ${CONFIG}"

echo "==> Step 2/3: ingest data into Virtuoso (~5 min)..."
inside "python fedshop/benchmark.py ingest ${CONFIG}"

echo "==> Step 3/3: generate queries (~10 min)..."
inside "python fedshop/benchmark.py generate queries ${CONFIG} --rerun-incomplete"

echo ""
echo "Done."
echo "Results: ${HOST_EXPERIMENTS}/bsbm/benchmark/generation/"
echo "Data:    ${HOST_EXPERIMENTS}/bsbm/model/dataset/"
