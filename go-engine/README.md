# fedshop-go

`fedshop-go` is the standalone federated SPARQL query engine used by the local
`fedshop-py` benchmark pipeline.

It implements the SPARQL surface used by the twelve FedShop templates, remote
SPARQL execution, hash and bound joins, ASK-based source selection with a
query-local cache, exclusive endpoint groups, endpoint predicate summaries,
cost-aware ordering, and strict or explicitly partial failure handling.

## Build and test

```bash
GOCACHE=$PWD/.gocache go test -race ./...
GOCACHE=$PWD/.gocache go build -o fedshop-go ./cmd/fedshop-go
```

## Query

```bash
./fedshop-go query \
  --config target/config/config_batch0.ttl \
  --query query.sparql \
  --out-result results.txt \
  --out-source-selection source_selection.txt \
  --query-plan query_plan.txt \
  --stats engine_stats.json \
  --selector ask --cache memory --join bind \
  --http-proxy http://localhost:5555 \
  --max-concurrency 4 --bind-batch-size 20 --retry-count 2
```

The explicit proxy routes endpoint traffic through the FedShop measurement
proxy. Retries apply only to transient transport failures and HTTP 502, 503, or
504 responses; the command deadline still bounds the complete query.

The original FedShop cache lifecycle is preserved: each process starts cold,
and cache reuse happens only within that query.

## Metadata experiment

```bash
./fedshop-go summarize \
  --config target/config/config_batch0.ttl \
  --output target/summary/summary_batch0.json

./fedshop-go query \
  --config target/config/config_batch0.ttl \
  --query query.sparql \
  --out-result results.txt \
  --out-source-selection source_selection.txt \
  --query-plan query_plan.txt \
  --stats engine_stats.json \
  --selector summary \
  --summary target/summary/summary_batch0.json \
  --planner cost --join bind
```

Summary construction records its own elapsed time, request count, and transfer
volume in the summary JSON; those costs are separate from per-query metrics.
