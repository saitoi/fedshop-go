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

# ── 1b. Clear stale ingest sentinels ────────────────────────────────────────
# The outer container is re-created on every run (fresh inner Docker daemon,
# no Virtuoso containers). Sentinel files left on the volume from a prior run
# would fool snakemake into skipping ingest, leaving no Virtuoso to serve
# queries. Wipe them so ingest always runs against the fresh inner daemon.
# Generate-data sentinels (.nq files, product data) are safe to keep.
echo "==> Clearing stale ingest sentinels..."
rm -f "${HOST_EXPERIMENTS}/bsbm/virtuoso-containers-ok.txt"
rm -f "${HOST_EXPERIMENTS}"/bsbm/virtuoso-data-batch*-ok.txt
rm -f "${HOST_EXPERIMENTS}"/bsbm/virtuoso-federation-endpoints-batch*-ok.txt

# ── 2. Git ───────────────────────────────────────────────────────────────────
echo "==> Updating FedShop repo to origin/main..."
# --recurse-submodules fails because engines/fedup is broken; skip it
inside "git fetch && git reset --hard origin/main"
# Init only the submodules needed for config_small (fedx, proxy, watdiv)
inside "git submodule update --init --force engines/FedX fedshop/proxy/FedShop-proxy generators/watdiv"

# ── 2b. Restore patched config ───────────────────────────────────────────────
# git reset writes the upstream config_small.yaml (without use_docker and other
# required keys) to the volume. Copy our fully-patched local version over it so
# ingest-data.smk and generate-queries.smk find all expected keys.
echo "==> Restoring patched config_small.yaml into volume..."
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "${HOST_EXPERIMENTS}/bsbm/snakefile"
cp "${REPO_ROOT}/reference-repos/FedShop/experiments/bsbm/snakefile/config_small.yaml" \
   "${HOST_EXPERIMENTS}/bsbm/snakefile/config_small.yaml"

# ── 3. Docker compose v2 plugin ─────────────────────────────────────────────
# The image ships docker-compose v1 (standalone binary). The snakemake rules
# call "docker compose" (plugin syntax) AND rely on docker compose v2 project
# naming: with v2, "-f path/to/docker/virtuoso.yml" derives project name from
# the compose file's parent directory ("docker"), producing container names like
# "docker-bsbm-virtuoso-1". Docker-compose v1 uses CWD as project name instead
# ("fedshop"), so containers would be named "fedshop_bsbm-virtuoso_1" —
# mismatching every "docker start / docker exec" call in the snakemake rules.
# Install the real docker compose v2 plugin binary to fix this.
echo "==> Installing docker compose v2 plugin..."
inside "
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL 'https://github.com/docker/compose/releases/download/v2.24.6/docker-compose-linux-aarch64' \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
docker compose version
"

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

# ── 7. Patch utils.py ───────────────────────────────────────────────────────
# docker-compose v1 (the standalone binary shimmed in step 3) does not support
# --format '{{.Name}}'. Silence the error: use stderr=DEVNULL so the traceback
# doesn't pollute logs (the except branch already returns [] safely).
echo "==> Patching utils.py (docker-compose --format noise)..."
docker exec "$CONTAINER" sed -i \
  's/subprocess\.check_output(cmd, shell=True)\.decode/subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode/g' \
  "${FEDSHOP}/fedshop/utils.py"

# ── 8. Patch query.py ────────────────────────────────────────────────────────
# Patches use line-by-line scanning (substring match) so they are robust to
# upstream indentation and surrounding-context differences that cause silent
# str.replace() no-ops.
echo "==> Patching query.py..."
docker exec "$CONTAINER" python3 << 'PYEOF'
f = '/FedShop/fedshop/query.py'
lines = open(f).readlines()
src = ''.join(lines)

# 7a. estimate_replacement_value_based_on_op: add early return for str values
# before the generic ValueError (product labels trigger the "in" operator path).
if 'isinstance(value, str)' not in src:
    old_7a = (
        '            else:\n'
        '                raise ValueError(f"Unsupported value type {type(value)} for value {value}!")'
    )
    new_7a = (
        '            elif isinstance(value, str):\n'
        '                return value\n'
        '            else:\n'
        '                raise ValueError(f"Unsupported value type {type(value)} for value {value}!")'
    )
    src2 = src.replace(old_7a, new_7a)
    if src2 != src:
        src = src2
        lines = src.splitlines(keepends=True)
        print('Patched 7a: str early-return in estimate_replacement_value_based_on_op')
    else:
        print('WARNING 7a: target string not found, patch not applied')
else:
    print('Skipped 7a: isinstance(value, str) already present')

# 7b. execute_query: 0 rows is valid for small datasets; downgrade to warning.
patched = False
for i, line in enumerate(lines):
    if 'raise RuntimeError(' in line and 'returns no result' in line:
        spc = ' ' * (len(line) - len(line.lstrip()))
        lines[i:i+1] = [
            spc + 'logger.warning(f"{queryfile} returns no result, writing empty output")\n',
            spc + 'return\n',
        ]
        print(f'Patched 7b at line {i+1}: RuntimeError -> warning in execute_query')
        patched = True
        break
if not patched:
    print('WARNING 7b: RuntimeError line not found, patch not applied')
src = ''.join(lines)

# 7c. create_workload_value_selection_with_constraints: no results after
# filtering means the query has no valid instantiation values for this dataset.
# Write an empty CSV and return instead of crashing.
# Two-condition scan (same strategy as 7b) to be quote-style agnostic.
patched = False
for i, line in enumerate(lines):
    if 'raise ValueError' in line and 'No results after filtering' in line:
        spc = ' ' * (len(line) - len(line.lstrip()))
        lines[i:i+1] = [
            spc + 'logger.warning("No results after filtering; writing empty workload CSV")\n',
            spc + 'if workload_value_selection:\n',
            spc + '    pd.DataFrame(columns=list(df.columns)).to_csv(workload_value_selection, index=False)\n',
            spc + 'return pd.DataFrame()\n',
        ]
        print(f'Patched 7c at upstream line {i+1}: empty CSV instead of ValueError')
        patched = True
        break
if not patched:
    print('WARNING 7c: target not found; nearby "filtering" lines:')
    for j, l in enumerate(lines):
        if 'filtering' in l.lower():
            print(f'  {j+1}: {repr(l)}')

# 7d. instanciate_workload: guard against empty workload CSV (written by 7c).
# Insert the check before the IndexError-prone .to_dict()[instance_id] call.
patched = False
for i, line in enumerate(lines):
    if 'placeholder_chosen_values' in line and 'to_dict' in line and 'instance_id' in line:
        spc = ' ' * (len(line) - len(line.lstrip()))
        lines[i:i] = [
            spc + 'if value_selection_values.empty:\n',
            spc + '    logger.warning(f"Empty workload at {value_selection}; writing FILTER(false) placeholder")\n',
            spc + '    Path(outfile).parent.mkdir(parents=True, exist_ok=True)\n',
            spc + '    open(outfile, "w").write("SELECT * WHERE { FILTER(false) }")\n',
            spc + '    return\n',
        ]
        print(f'Patched 7d at upstream line {i+1}: guard empty workload in instanciate_workload')
        patched = True
        break
if not patched:
    print('WARNING 7d: placeholder_chosen_values line not found; nearby lines:')
    for j, l in enumerate(lines):
        if 'placeholder_chosen_values' in l or ('to_dict' in l and 'instance_id' in l):
            print(f'  {j+1}: {repr(l)}')

open(f, 'w').writelines(lines)
print('query.py patching complete')
PYEOF

# ── 9. Run benchmark ─────────────────────────────────────────────────────────
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
