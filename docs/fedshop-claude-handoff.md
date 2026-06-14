# FedShop / FedX Handoff Notes

This document summarizes the FedShop/FedX debugging work done in this workspace so another coding agent can continue without rebuilding the context from the chat.

Workspace root:

```bash
/Users/pedrosaito/fedshop-go
```

Main benchmark checkout:

```bash
/Users/pedrosaito/fedshop-go/reference-repos/FedShop
```

## Goal

The work started with running:

```bash
./scripts/pyfedx-small.sh setup
```

and debugging failures. The work then shifted to running the original FedShop/FedX benchmark path for individual FedShop BSBM queries, especially `q05`, using batch `0`, instance `0`, and the smoke config:

```bash
reference-repos/FedShop/experiments/bsbm/snakefile/config_small.yaml
```

The current practical goal is to run individual FedX benchmark queries reliably against the local Docker-based FedShop/Virtuoso setup.

## Important Project Facts

- FedShop benchmark code lives in `reference-repos/FedShop`.
- Local wrappers live in `scripts/`.
- Prefer `./scripts/fedshop-run.sh` from the repository root. It wraps FedShop with `uv run` and avoids relying on a globally installed `python`.
- The evaluation artifacts are under:

```bash
reference-repos/FedShop/experiments/bsbm/benchmark/evaluation
```

- FedX original source was cloned/built under:

```bash
reference-repos/FedShop/engines/FedX
```

- The FedShop FedX adapter expects the older standalone FedX wrapper, not modern RDF4J FedX.

## Docker State And Commands

The local benchmark uses two Docker services:

- Virtuoso: `docker-bsbm-virtuoso-1`
- FedShop proxy: `docker-fedshop-proxy-1`

Start them from the workspace root:

```bash
docker compose -f reference-repos/FedShop/experiments/bsbm/docker/virtuoso.yml up -d
docker compose -f reference-repos/FedShop/experiments/bsbm/docker/proxy.yml up -d
```

Check container status:

```bash
docker ps --filter name=bsbm-virtuoso --filter name=fedshop-proxy
```

Check proxy health:

```bash
curl http://localhost:5555/get-stats
```

Expected response shape:

```json
{
  "NB_ASK": 0,
  "NB_HTTP_REQ": 0,
  "DATA_TRANSFER": 0
}
```

If the proxy hangs on `/reset` or `/get-stats`, restart only the proxy:

```bash
docker restart docker-fedshop-proxy-1
```

Check Virtuoso:

```bash
curl -s "http://localhost:8890/sparql?query=ASK%20%7B%20?s%20?p%20?o%20%7D"
```

## Individual Query Evaluation Command

Use this pattern from `/Users/pedrosaito/fedshop-go`:

```bash
Q=q05
ATTEMPT=3

./scripts/fedshop-run.sh evaluate \
  --config experiments/bsbm/snakefile/config_small.yaml \
  --engine fedx \
  --query "$Q" \
  --instance 0 \
  --batch 0 \
  --attempt "$ATTEMPT" \
  --rerun-incomplete
```

To run multiple queries individually while keeping batch/config equal:

```bash
ATTEMPT=3
for Q in q01 q02 q03 q04 q05 q06 q07 q08 q09 q10; do
  ./scripts/fedshop-run.sh evaluate \
    --config experiments/bsbm/snakefile/config_small.yaml \
    --engine fedx \
    --query "$Q" \
    --instance 0 \
    --batch 0 \
    --attempt "$ATTEMPT" \
    --rerun-incomplete
done
```

Use a new `ATTEMPT` for a fresh run. If files for the same query/instance/batch/attempt already exist and are up to date, Snakemake may skip execution.

## q05 Latest Verified Result

The latest verified q05 run used:

```bash
./scripts/fedshop-run.sh evaluate \
  --config experiments/bsbm/snakefile/config_small.yaml \
  --engine fedx \
  --query q05 \
  --instance 0 \
  --batch 0 \
  --attempt 2 \
  --rerun-incomplete
```

Snakemake reported that requested files were present and up to date after the prior successful run.

q05 output directory:

```bash
reference-repos/FedShop/experiments/bsbm/benchmark/evaluation/fedx/q05/instance_0/batch_0/attempt_2
```

Generated files include:

```bash
stats.csv
results.txt
results.csv
source_selection.txt
provenance.csv
query_plan.txt
```

Recorded `stats.csv` row:

```csv
engine,query,instance,batch,attempt,source_selection_time,planning_time,ask,exec_time,http_req,data_transfer
fedx,q05,0,0,2,245.0,1.0,0.0,316.0,0.0,0.0
```

Recorded aggregate `metrics.csv` row:

```csv
attempt,engine,query,instance,batch,nb_results,nb_distinct_sources,relevant_sources_selectivity,tpwss,avg_rwss,min_rwss,max_rwss,source_selection_time,planning_time,ask,exec_time,http_req,data_transfer
2,fedx,q05,0,0,,20,1.0,200,,,,245.0,1.0,0.0,316.0,0.0,0.0
```

`results.csv` is empty for this q05 run, meaning FedX completed but produced no result rows.

## What Was Found

### Initial Full q01-q10 FedX Run Failed

A previous full q01-q10 run completed in the Snakemake sense but every query produced failure rows:

```text
source_selection_time=error_runtime
planning_time=error_runtime
exec_time=error_runtime
ask=0
http_req=0
data_transfer=0
```

The benchmark files existed, but the actual FedX query runs were failures.

### Proxy / Endpoint Routing Was The First Runtime Problem

The original route caused the proxy to forward to `localhost:342xx` from inside the proxy container. Inside a container, that resolves to the proxy container itself, so requests failed with connection refused.

Later debugging switched batch0 endpoints toward host-accessible Virtuoso routes. Direct Virtuoso probes against `localhost:8890` and the generated per-member paths worked.

The remaining proxy issue observed during q05 was that `/reset` and `/get-stats` can hang if the proxy process is wedged. When that happens, FedX appears to stall before Java starts because `fedshop/engines/fedx.py` calls:

```python
requests.get(proxy_server + "reset")
```

without an explicit timeout.

Restarting `docker-fedshop-proxy-1` fixed that state.

### q04 And q09 Worked Manually

Manual direct FedX runs for q04 and q09 reached Java/FedX and completed successfully after routing fixes. This established that the FedX runtime path itself could work.

### q05 Engine Run Worked, Then Post-Processing Failed

For q05, the FedX Java execution completed successfully, but the benchmark workflow failed in `transform_provenance`.

Root cause: q05 source selection includes an empty list for `tp0` and 20 sources for the other triple patterns. The original provenance transform had a padding helper but did not call it, then tried to reshape mixed-length lists with:

```python
in_df.set_index("tp_name")["source_selection"] \
    .to_frame().T \
    .apply(pd.Series.explode) \
    .reset_index(drop=True)
```

That failed in pandas with:

```text
ValueError: cannot reindex on an axis with duplicate labels
```

The final narrow fix restored the original reshape path and only re-enabled padding before the reshape.

## Current FedX Adapter Change

File:

```bash
reference-repos/FedShop/fedshop/engines/fedx.py
```

Current functional changes:

1. Java `http.nonProxyHosts` now includes local endpoints:

```text
host.docker.internal|localhost|127.0.0.1
```

This prevents Java from routing local Virtuoso endpoint calls through the FedShop proxy as the JVM outbound HTTP proxy.

2. `transform_provenance` now calls the existing `pad()` helper before exploding source-selection lists:

```python
max_length = in_df["source_selection"].apply(len).max()
in_df["source_selection"] = in_df["source_selection"].apply(pad)
out_df = in_df.set_index("tp_name")["source_selection"] \
    .to_frame().T \
    .apply(pd.Series.explode) \
    .reset_index(drop=True)
```

This keeps the upstream reshape style and only fixes empty/short source-selection lists.

A broader attempted change that built `out_df` directly from a dict was rejected by the user and replaced with the narrow padding fix above.

## Other Current Local Changes

There are additional tracked changes in the workspace. Some are intentional local benchmark setup changes, and some came from earlier debugging.

### Parent Repository Changes

Files changed in `/Users/pedrosaito/fedshop-go`:

```bash
scripts/fedshop-uv-requirements.txt
scripts/pyfedx.py
```

`scripts/fedshop-uv-requirements.txt`:

- Added dependencies required by FedShop commands:
  - `fasttext-langdetect==1.0.3`
  - `nltk==3.9b1`
  - `iso639-lang==2.1.0`
  - `wget==3.2`

`scripts/pyfedx.py`:

- Parser now accepts `SELECT ... { ... }` without explicit `WHERE`.
- `where_body()` uses the updated `SELECT_RE` and reports `missing graph pattern block`.

This was done because generated FedShop queries may omit explicit `WHERE`. That is allowed by SPARQL grammar, so accepting omitted `WHERE` is not considered a semantic problem.

### FedShop Checkout Changes

Important changed files in `reference-repos/FedShop`:

```bash
experiments/bsbm/docker/proxy.yml
experiments/bsbm/docker/virtuoso.yml
experiments/bsbm/snakefile/config_small.yaml
fedshop/algebra/rdflib_algebra.py
fedshop/benchmark.py
fedshop/engines/fedx.py
fedshop/query.py
snakemake/ingest-data.smk
```

`experiments/bsbm/docker/proxy.yml`:

- Removed host networking.
- Added explicit port mapping:

```yaml
ports:
  - "5555:5555"
```

`experiments/bsbm/docker/virtuoso.yml`:

- Removed host networking.
- Added explicit port mappings:

```yaml
ports:
  - 1111:1111
  - 8890:8890
  - 34200-34219:34200-34219
```

- Reduced memory settings for Docker Desktop:

```yaml
VIRT_Parameters_NumberOfBuffers: 170000
VIRT_Parameters_MaxDirtyBuffers: 125000
VIRT_Parameters_MaxQueryMem: 512M
```

`experiments/bsbm/snakefile/config_small.yaml`:

- `use_docker: true`
- Added local Virtuoso/default endpoint settings.
- Added proxy host/port/container fields.
- Corrected FedX engine directory from:

```yaml
dir: "engines/FedX/target"
```

to:

```yaml
dir: "engines/FedX"
```

`snakemake/ingest-data.smk`:

- Endpoint/proxy target handling was changed during Docker Desktop routing work.
- Also changed batch creation to scale to `len(BATCHES)` instead of `N_BATCH`.

Important caveat: the handoff agent should inspect the current file before changing it. At one point the intended working host route for local Java was `localhost:8890`, while one current diff version shows `host.docker.internal:8890` in `ingest-data.smk`. Confirm generated mapping files and direct endpoint health before running more queries.

`fedshop/benchmark.py`:

- Generation batching was changed to use the configured `batch` length instead of always `N_BATCH`.

`fedshop/algebra/rdflib_algebra.py`:

- Added date literal handling using `XSD.date` for strings matching `YYYY-MM-DD`.
- Translator now emits `-*-SELECT-*- {` instead of `-*-SELECT-*- WHERE {`.

This can affect generated query text. The user noted that omitted `WHERE` is valid per SPARQL.

`fedshop/query.py`:

- Placeholder replacement logic was changed to handle inequality direction more carefully.
- `=` and `in` return the same value.
- `!=` now returns `None` and falls back to candidate selection.
- For `<`, `<=`, `>`, `>=`, the epsilon direction depends on whether the placeholder is on the left or right side.

This can affect generated workload constants.

## Generated / Runtime Artifacts

Important generated files:

```bash
reference-repos/FedShop/engines/FedX/target/config/config_batch0.ttl
reference-repos/FedShop/experiments/bsbm/virtuoso-proxy-mapping-batch0.json
reference-repos/FedShop/experiments/bsbm/benchmark/evaluation/metrics.csv
reference-repos/FedShop/experiments/bsbm/benchmark/evaluation/eval_stats_batch0.csv
reference-repos/FedShop/experiments/bsbm/benchmark/evaluation/fedx/q05/instance_0/batch_0/attempt_2/
```

FedX `config_batch0.ttl` should contain `sd:endpoint` entries for 20 batch0 endpoints:

- `vendor0` through `vendor9`
- `ratingsite0` through `ratingsite9`

The endpoint URLs should match the currently running Virtuoso route. Verify before debugging query failures.

## Useful Debug Commands

Inspect q05 artifacts:

```bash
cd /Users/pedrosaito/fedshop-go/reference-repos/FedShop

sed -n '1,40p' experiments/bsbm/benchmark/evaluation/fedx/q05/instance_0/batch_0/attempt_2/stats.csv
sed -n '1,20p' experiments/bsbm/benchmark/evaluation/fedx/q05/instance_0/batch_0/attempt_2/results.csv
sed -n '1,20p' experiments/bsbm/benchmark/evaluation/fedx/q05/instance_0/batch_0/attempt_2/provenance.csv
sed -n '1,40p' experiments/bsbm/benchmark/evaluation/metrics.csv
```

Check q05 generated query:

```bash
sed -n '1,220p' experiments/bsbm/benchmark/generation/q05/instance_0/injected.sparql
```

Check q05 raw source selection:

```bash
sed -n '1,200p' experiments/bsbm/benchmark/evaluation/fedx/q05/instance_0/batch_0/attempt_2/source_selection.txt
```

Check source count per q05 triple pattern:

```bash
awk -F'"' 'NR>1 {n=gsub(/StatementSource/,"",$4); print NR-1, n}' \
  experiments/bsbm/benchmark/evaluation/fedx/q05/instance_0/batch_0/attempt_2/source_selection.txt
```

Directly test provenance transform:

```bash
uv run --no-project \
  --python 3.8 \
  --with-requirements /Users/pedrosaito/fedshop-go/scripts/fedshop-uv-requirements.txt \
  --script fedshop/engines/fedx.py transform-provenance \
  experiments/bsbm/benchmark/evaluation/fedx/q05/instance_0/batch_0/attempt_2/source_selection.txt \
  experiments/bsbm/benchmark/evaluation/fedx/q05/instance_0/batch_0/attempt_2/provenance_check.csv \
  experiments/bsbm/benchmark/generation/q05/instance_0/composition.json
```

## Caveats For The Next Agent

- Do not interpret Snakemake completion as benchmark success. Inspect `stats.csv` and `metrics.csv`.
- Use a fresh `--attempt` when validating a query run, otherwise Snakemake may skip because outputs are already present.
- The FedShop proxy can hang. If `curl -m 5 http://localhost:5555/get-stats` times out, restart `docker-fedshop-proxy-1`.
- q05 currently completes but returns no result rows.
- The FedX adapter change to `http.nonProxyHosts` affects FedX evaluation only. It does not alter the FedX Java engine logic.
- The provenance padding fix affects FedX post-processing only. It does not alter FedX query execution.
- Changes in `rdflib_algebra.py`, `query.py`, and `benchmark.py` can affect workload generation or setup, so avoid treating them as FedX-engine-only changes.
- The nested FedShop checkout has submodule/symlink oddities. Running `git status --short` inside `reference-repos/FedShop` can fail with:

```text
error: expected submodule path 'engines/ANAPSID' not to be a symbolic link
```

Use targeted `git diff -- <path>` commands if status fails.

## Recommended Next Steps

1. Restart Docker services if the environment was reset.
2. Confirm proxy and Virtuoso health with `curl`.
3. Use a fresh attempt number and run one query at a time.
4. Inspect per-query `stats.csv`, `results.csv`, `source_selection.txt`, and `provenance.csv`.
5. If a query hangs before Java starts, check proxy `/reset`.
6. If a query reaches Java but fails, capture direct FedX/Maven output instead of relying only on Snakemake logs.
7. If provenance transform fails for another query, keep changes narrow and preserve the upstream reshape path unless there is a stronger reason to replace it.
