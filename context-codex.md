# FedShop Go Engine Continuation Context

Last updated: 2026-06-22, America/Sao_Paulo.

## Objective

This workspace contains a Python reimplementation of the FedShop benchmark and a minimal federated SPARQL engine in Go. The immediate objective has been to make `fedshop-go` produce correct, FedShop-compatible artifacts and metrics for the smoke configuration while comparing its design with the reference engines.

Read these files first:

- `AGENTS.md` for repository workflow and constraints.
- `docs/fedshop-go-engine-comparison.md` for the architectural comparison with FedX, CostFed/Hibiscus, Semagrow, SPLENDID, ANAPSID, FedUP, and RSA.
- `fedshop-py/config/config_small.yaml` for the active two-batch smoke benchmark.
- `fedshop-py/benchmark/metrics.csv` for the current result matrix.
- `fedshop-go-run.log` for the original failed run.

## Critical Worktree Warning

The worktree is heavily dirty and contains many user-owned modifications and untracked files. Do not clean, reset, checkout, or remove unrelated paths. In particular, `go-engine/`, much of `fedshop-py/config/`, benchmark output, data, and tests are currently untracked. Inspect targeted diffs and edit only files required by the task.

## Current Verified Benchmark State

Current `fedshop-go` rows in `fedshop-py/benchmark/metrics.csv`:

| Query | Status | Attempts | Notes |
|---|---:|---:|---|
| q01 | ok | 4 | Valid zero-result cases |
| q02 | timeout | 4 | Unresolved; expensive result/intermediate volume |
| q03 | ok | 4 | Valid zero-result cases |
| q04 | ok | 4 | Valid zero-result cases |
| q05 | error_runtime | 4 | Unresolved; caused Virtuoso OOM in the combined run |
| q06 | ok | 4 | Exact reference multiset match |
| q07 | ok | 4 | Exact reference multiset match |
| q08 | ok | 4 | Exact reference multiset match, including zero rows |
| q09 | ok | 4 | Now generates instances and one expected result per run |
| q10 | ok | 4 | Exact reference multiset match, valid zero rows |
| q11 | ok | 4 | Exactly 10 results per run |
| q12 | ok | 4 | Exact reference multiset match |

All 28 q06-q12 combinations were run individually after an OOM, with `metrics.csv` recomputed after each query. Their normalized CSV result multisets exactly matched the regenerated reference CSVs.

Do not rerun the full q01-q12 sequence until q05 is contained. In the last combined run, q05 OOM-killed Virtuoso, causing q06-q12 to fail only because the endpoint disappeared. Docker inspection confirmed:

```text
status=exited exit=137 oom=true memory=0
```

The container had no explicit Docker memory limit. Reduced Virtuoso internal settings alone did not prevent q05 from exhausting the roughly 3.8 GiB Docker VM.

## Root Causes Already Identified and Fixed

### Graph routing

The original configuration used `/vendorN/sparql` and `/ratingsiteN/sparql` paths. Virtuoso host registration is keyed by host rather than path, so endpoints resolved to the wrong/shared graph. q11 returned 4,000/16,000 rows instead of 10.

`fedshop-py/src/fedshop/ingest.py` now emits graph-scoped endpoints:

```text
http://localhost:8890/sparql?default-graph-uri=<encoded graph IRI>
```

The Go adapter converts `host.docker.internal` to `localhost` for the host-run Go binary. Isolated q11 verified the correction with 10 rows for every instance/batch.

### Stale benchmark artifacts and misleading metrics

Failed reruns previously preserved old `results.csv`, provenance, and engine JSON. This made failed q11 rows appear to contain 4,000/16,000 results.

- `fedshop-py/src/fedshop/evaluate.py` truncates every attempt artifact before execution.
- `fedshop-py/src/fedshop/metrics.py` derives a `status` from `stats.csv` and ignores result/provenance artifacts for explicit failures.
- `fedshop-py/src/fedshop/engines/fedshop_go.py` truncates raw outputs and deletes stale engine stats.

Current invariant: failed attempts have blank derived metrics, while successful zero-row queries remain `status=ok, nb_results=0`.

### Query generation cache and entity selection

Batch 0 now rebuilds value-selection queries and resamples workload values instead of trusting empty/stale caches. Reference results are recomputed for every batch.

q08 and q10 previously selected `Producer` IRIs for `ProductXYZ` because the reduced value-selection BGP retained only `owl:sameAs`. `build_value_selection_query` now retains one incoming domain edge:

- q08: `reviewFor` identifies reviewed products.
- q10: `product` identifies products referenced by offers.

q09 previously produced an empty workload even though ratingsite N-Quads contain `rev:reviewer` triples. The unscoped Virtuoso default dataset was incomplete/pathological. Value selection now queries graph-scoped member endpoints directly.

### SPARQLWrapper graph parameters

Embedding encoded `default-graph-uri` directly in a SPARQLWrapper endpoint caused double encoding and Virtuoso `22023` errors. `fedshop-py/src/fedshop/sparql.py` now:

1. Parses endpoint query parameters.
2. Constructs SPARQLWrapper with the base endpoint.
3. Calls `addDefaultGraph` for each graph URI.

### Reference-result correctness and OOM avoidance

The unscoped default endpoint produced incomplete reference CSVs, such as one q06 row when the federation contained 4 or 14 matches.

Source-local reference queries use graph-scoped fan-out and deduplicate identical rows. The current source-local set is:

```python
{"q06", "q08", "q09", "q10", "q11", "q12"}
```

q07 remains aggregate because its OPTIONAL branches intentionally span vendor and ratingsite sources. Reference execution also prunes fan-out when a bound source-owned IRI identifies one graph, e.g. a `vendor0` offer or `ratingsite0` review.

### Go execution correctness

The executor now propagates incoming bindings into nested OPTIONAL and UNION groups. It also deduplicates identical bindings returned by replicated sources before joining.

The endpoint JSON decoder canonicalizes XSD decimal/double/float lexical values. This converts Virtuoso JSON artifacts such as `2787.7100000000000364` to `2787.71`, matching Virtuoso CSV reference output for q07/q12.

The HTTP client supports bounded retries for transport failures and HTTP 502/503/504, with context-aware exponential backoff. CLI/config options include:

- `--max-concurrency`
- `--bind-batch-size`
- `--retry-count`
- `--http-proxy`

The Python adapter defaults to direct endpoint execution. Proxy use is opt-in because the Java proxy was unreliable for this host/container topology. Engine-owned JSON counters populate HTTP request/data-transfer metrics in direct mode.

## Main Implementation Locations

### Go engine

- `go-engine/cmd/fedshop-go`: executable entry point.
- `go-engine/internal/cli`: command and flag handling.
- `go-engine/internal/sparql`: minimal FedShop-oriented SPARQL parser.
- `go-engine/internal/federation`: ASK/summary source selection.
- `go-engine/internal/planner`: source-count and metadata-aware ordering.
- `go-engine/internal/executor`: bind/hash execution, filters, OPTIONAL, UNION, projection, DISTINCT, ordering, slicing.
- `go-engine/internal/endpoint`: SPARQL protocol, retries, numeric normalization, counters.
- `go-engine/internal/artifact`: FedShop-compatible results, plans, source selection, and stats.
- `go-engine/internal/app`: orchestration for query and summary commands.

### Python benchmark

- `fedshop-py/src/fedshop/ingest.py`: graph loading and endpoint mapping.
- `fedshop-py/src/fedshop/query.py`: value selection, instantiation, reference execution.
- `fedshop-py/src/fedshop/sparql.py`: SPARQLWrapper boundary.
- `fedshop-py/src/fedshop/evaluate.py`: per-attempt lifecycle and artifact cleanup.
- `fedshop-py/src/fedshop/metrics.py`: status-aware aggregation.
- `fedshop-py/src/fedshop/engines/fedshop_go.py`: Go adapter.
- `fedshop-py/run-benchmark.sh`: end-to-end local pipeline.

## Test-Driven Development History

The recent fixes were developed red-green. Regression tests cover:

- Graph-scoped endpoint registration and repeatable N-Quads loading.
- Empty/stale workload caches.
- q08/q10 entity-identifying value-selection edges.
- Graph-scoped fallback/primary value selection.
- SPARQLWrapper default graph extraction.
- Source-local reference fan-out, deduplication, and bound-IRI endpoint pruning.
- Batch reference overwrites.
- Artifact truncation and failure-aware metrics.
- Retry behavior, explicit proxy behavior, and CLI flags.
- OPTIONAL/UNION binding propagation.
- Replicated binding deduplication.
- Numeric lexical canonicalization.

## Fresh Verification Evidence

The last complete verification run succeeded:

```text
Python pytest: 101 passed, 8 deprecation warnings
Ruff: All checks passed
Go: go test -race ./... passed
Go: go vet ./... passed
Go: go build ./cmd/fedshop-go passed
Metrics: 28 q06-q12 rows, all status=ok
Result verification: all 28 result multisets match
Virtuoso after individual runs: status=running, oom=false, exit=0
```

Commands:

```bash
cd fedshop-py
UV_CACHE_DIR=/tmp/fedshop-uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/fedshop-uv-cache uv run ruff check \
  src/fedshop/query.py src/fedshop/sparql.py \
  tests/test_query_generation.py tests/test_sparql.py

cd ../go-engine
GOCACHE=$PWD/.gocache go test -race ./...
GOCACHE=$PWD/.gocache go vet ./...
GOCACHE=$PWD/.gocache go build -o /tmp/fedshop-go-verify ./cmd/fedshop-go
```

## Safe Benchmark Workflow After OOM

Docker Desktop can respond slowly after Virtuoso is OOM-killed. Do not interpret a quiet `docker version` as an immediate timeout; it previously completed after roughly two minutes. After an OOM, Docker commands may take several minutes.

Start/recover services:

```bash
cd fedshop-py
docker compose -f docker/virtuoso.yml up -d
docker compose -f docker/proxy.yml up -d
curl -fsS 'http://localhost:8890/sparql?query=ASK+%7B+%3Fs+%3Fp+%3Fo+%7D'
```

Run one query and update metrics immediately:

```bash
./run-benchmark.sh \
  --engine fedshop-go \
  --query q09 \
  --skip-docker --skip-generate --skip-ingest --skip-queries
```

Regenerate one query's batch references:

```bash
UV_CACHE_DIR=/tmp/fedshop-uv-cache uv run fedshop query run-all \
  --config config/config_small.yaml \
  --bench-dir benchmark \
  --batch-id 0 \
  --query-name q09
```

For q06-q12, prefer one query per invocation and recompute metrics after each. This is the verified OOM-safe workflow.

## Remaining Work

### q02 timeout

q02 still times out in all four smoke combinations. Its earlier reference artifacts contained extremely large result volumes. Diagnose source selection, intermediate cardinality, and filter/projection pushdown before increasing timeouts.

### q05 Virtuoso OOM

q05 returns only five final rows but creates large intermediate similarity joins. The combined run OOM-killed Virtuoso after q02 timeouts. Required next investigation:

1. Run q05 alone on a freshly restarted Virtuoso.
2. Compare `max_concurrency=1`, `bind_batch_size=1` against current `4/20` without changing multiple variables simultaneously.
3. Capture per-triple row counts and request sizes.
4. Determine whether local FILTER evaluation causes avoidable intermediate expansion.
5. Prefer filter pushdown, better join ordering, exclusive grouping, or bounded request shaping over allocating more Docker memory.

Do not claim the full q01-q12 benchmark is fixed until q02 and q05 pass without taking Virtuoso down.

## Design Position Relative to Reference Engines

The Go engine is intentionally smaller than the reference systems:

- FedX: closest execution model; bound joins, source selection, exclusive groups.
- CostFed/Hibiscus: stronger statistics and source pruning than current Go metadata.
- Semagrow: more general metadata-driven planning and decomposition.
- SPLENDID: VoID/statistics-based optimization.
- ANAPSID: adaptive execution and endpoint-delay resilience not yet implemented here.
- FedUP/RSA: stronger source-assignment rewriting and SERVICE-query baselines.

The next architectural priority after q02/q05 correctness is cardinality-aware planning and safe filter pushdown, not broader SPARQL syntax.

