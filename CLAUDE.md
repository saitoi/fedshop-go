# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Goal

Build a minimal federated SPARQL query engine in Go that can be benchmarked via FedShop. The FedShop benchmark harness (`reference-repos/FedShop`) is the evaluation target; the Go engine must produce FedShop-compatible output files to be registered as a new engine adapter.

## Repository Layout

```
scripts/                      # Local wrappers for running FedShop
  fedshop-run.sh              # Main entry point: wraps FedShop via uv run
  fedshop-docker.sh           # Build/run the FedShop Docker image
  fedshop-link-updated-sources.sh  # Symlink updated engine sources into FedShop
  clone-query-engines.sh      # Clone current upstream engine repos
  fedshop-uv-requirements.txt # Lean Python deps (no fasttext) for uv runs
  pyfedx.py                   # Standalone single-file FedX runner (dev tool)

reference-repos/
  FedShop/                    # Benchmark harness (modified fork)
    experiments/bsbm/
      snakefile/config_small.yaml   # Smoke config: 2 batches, 2 instances, fedx+rsa
      snakefile/config.yaml         # Full config: all engines, 10 batches
      docker/virtuoso.yml           # Virtuoso container
      docker/proxy.yml              # FedShop proxy container (port 5555)
    fedshop/engines/fedx.py         # FedX adapter (Python) — model for new Go adapter
    benchmark/evaluation/           # Per-query output: stats.csv, results.csv, provenance.csv
    benchmark/generation/           # Generated queries: q*/instance_*/injected.sparql
  query-engines/              # Upstream engine source checkouts (cloned by script)

example-implementation/       # Minimal RSA-baseline Go engine (reference)
  cmd/fedshop-rsa-go/main.go
  internal/engine/            # parser, executor, join, output, types

docs/
  fedshop-benchmark.md        # Benchmark runbook
  fedshop-claude-handoff.md   # Detailed debug history and current state
  fedx-engine-guide.md        # Engine reading order and architecture notes
  fedshop-generated-data-and-queries.md  # Dataset model and query patterns

reference-papers/fedshop.pdf  # Source paper
```

## Common Commands

### FedShop Benchmark (run from repo root)

```bash
# Dry-run smoke plan (no execution):
scripts/fedshop-run.sh smoke

# Evaluate one query:
scripts/fedshop-run.sh evaluate \
  --config experiments/bsbm/snakefile/config_small.yaml \
  --engine fedx --query q05 --instance 0 --batch 0 --attempt 3 \
  --rerun-incomplete

# Generate data / queries:
scripts/fedshop-run.sh generate-data --config experiments/bsbm/snakefile/config.yaml
scripts/fedshop-run.sh generate-queries --config experiments/bsbm/snakefile/config.yaml

# Full pipeline:
scripts/fedshop-run.sh full --config experiments/bsbm/snakefile/config.yaml
```

`--attempt` must be incremented for a fresh run; Snakemake skips if outputs already exist.  
Use `FEDSHOP_UV_REQUIREMENTS=reference-repos/FedShop/requirements.txt` when `generate-queries` needs the full stack (including `fasttext`).

### Docker Services

```bash
# Start Virtuoso and FedShop proxy:
docker compose -f reference-repos/FedShop/experiments/bsbm/docker/virtuoso.yml up -d
docker compose -f reference-repos/FedShop/experiments/bsbm/docker/proxy.yml up -d

# Health checks:
curl -m 5 http://localhost:5555/get-stats       # proxy: expect {"NB_ASK":0,...}
curl -s "http://localhost:8890/sparql?query=ASK%20%7B%20?s%20?p%20?o%20%7D"  # Virtuoso

# If proxy hangs on /reset or /get-stats:
docker restart docker-fedshop-proxy-1

# FedShop Docker image:
scripts/fedshop-docker.sh build
scripts/fedshop-docker.sh shell   # interactive shell with workspace mounted
```

### Go Engine (example-implementation)

```bash
cd example-implementation
GOCACHE=$PWD/.gocache GOMODCACHE=$PWD/.gomodcache go test ./...
GOCACHE=$PWD/.gocache GOMODCACHE=$PWD/.gomodcache go build ./cmd/fedshop-rsa-go
```

## Architecture: FedShop Evaluation Flow

Each query evaluation goes through this chain:

1. **Snakemake** (via `fedshop/benchmark.py`) selects target files for a given engine/query/instance/batch/attempt.
2. **Python adapter** (`fedshop/engines/<engine>.py`) is called. It:
   - resets and checks the proxy (`/reset`, `/get-stats`)
   - generates a per-batch endpoint config (e.g. `config_batch0.ttl` for FedX)
   - launches the engine binary
   - calls `transform_results` and `transform_provenance` to convert output into FedShop CSV format
3. **Engine binary** runs the query against federation members, writes raw results + source selection.
4. **Outputs** land under `benchmark/evaluation/<engine>/<query>/instance_<i>/batch_<b>/attempt_<a>/`:
   - `stats.csv` — timing and HTTP metrics
   - `results.csv` — query result rows
   - `source_selection.txt` — which endpoints were selected per triple pattern
   - `provenance.csv` — reshaped source selection table
   - `query_plan.txt` — engine-specific plan

**Snakemake completion ≠ benchmark success.** Always inspect `stats.csv`; `error_runtime` in any field means the engine run failed.

## Architecture: FedX Adapter (model for Go adapter)

`reference-repos/FedShop/fedshop/engines/fedx.py` is the reference to follow when writing a new Go adapter. Key functions:

- `generate_config_file` — writes the endpoint list the engine reads at startup
- `run_benchmark` — sets up paths, calls `exec_fedx`, then post-processes
- `transform_provenance` — pads ragged source-selection lists before reshaping (contains a local fix; preserve the upstream `set_index/explode` reshape path)

The Java FedX entrypoint is `reference-repos/FedShop/engines/FedX/src/main/java/org/example/FedX.java`. The Go engine needs to produce the same output file shapes.

## Architecture: Go Engine (example-implementation)

`example-implementation` is the RSA baseline: it executes pre-assigned `SERVICE <endpoint> { BGP }` blocks without doing source selection. It is the simplest valid FedShop engine.

Key internal packages:
- `engine.Query` / `engine.ServiceBlock` / `engine.Binding` — core types (`types.go`)
- `parser.go` — SPARQL subset parser: PREFIX, SELECT [DISTINCT], LIMIT, SERVICE blocks
- `executor.go` — sends each SERVICE block to its endpoint via HTTP SPARQL, returns bindings
- `join.go` — natural hash join over shared variables
- `output.go` — writes FedShop-compatible results.csv, source_selection.csv, stats.csv, query_plan.txt

A full source-selection engine (the actual project goal) adds a source selector and planner before the executor step.

## FedShop Data Model (brief)

- Federation members: vendors (`vendor0`–`vendor9` per batch) and rating sites (`ratingsite0`–`ratingsite9`).
- Each batch adds 10 vendors + 10 rating sites; batch 0 = 20 endpoints, batch 9 = 200 endpoints.
- Entities use local URIs linked back to a global catalog via `owl:sameAs` — this is why most queries contain `owl:sameAs` joins.
- Query templates are in `reference-repos/FedShop/experiments/bsbm/queries/q*.sparql`; instantiated versions land in `benchmark/generation/q*/instance_*/injected.sparql`.

## Known Issues / Caveats

- The FedShop proxy (`docker-fedshop-proxy-1`) can wedge and hang on `/reset`. Restart it when `curl -m 5 http://localhost:5555/get-stats` times out.
- `git status --short` inside `reference-repos/FedShop` may fail with a submodule/symlink error; use `git diff -- <path>` instead.
- FedX is not linked by `fedshop-link-updated-sources.sh` because FedShop's adapter expects the old standalone `org.example.FedX` wrapper jar; current FedX is inside RDF4J and needs an adapter port.
- Current `fedshop/engines/fedx.py` has two local patches: `http.nonProxyHosts` for local endpoints, and a padding fix in `transform_provenance` before the `set_index/explode` reshape.
- `config_small.yaml` uses `use_docker: true` with explicit port mappings (not host networking).

## Reading Order for New Engine Work

1. `docs/fedshop-benchmark.md` — runbook
2. `docs/fedshop-claude-handoff.md` — full debug history and current local patches
3. `docs/fedx-engine-guide.md` — engine source reading order and size comparison table
4. `example-implementation/` — minimal working Go engine
5. `reference-repos/FedShop/fedshop/engines/fedx.py` — adapter to model
