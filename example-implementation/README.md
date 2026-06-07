# fedshop-rsa-go

`fedshop-rsa-go` is a minimal Go implementation of the simplest FedShop
baseline: RSA-style execution of queries that already contain SPARQL
`SERVICE <endpoint> { ... }` blocks.

It does not implement FedX/CostFed-style source selection or cost-based
optimization. The engine expects source assignment to have happened before
execution, then sends each service block to its endpoint, reads SPARQL CSV
results, naturally joins bindings on shared variables, and writes FedShop-like
outputs.

## Build

```bash
GOCACHE=$PWD/.gocache GOMODCACHE=$PWD/.gomodcache go test ./...
GOCACHE=$PWD/.gocache GOMODCACHE=$PWD/.gomodcache go build ./cmd/fedshop-rsa-go
```

## Run

```bash
./fedshop-rsa-go \
  --query service-query.sparql \
  --out-result results.csv \
  --out-source-selection source_selection.csv \
  --query-plan query_plan.txt \
  --stats stats.csv
```

Use `--noexec` to write plan/source/stats placeholders without contacting
endpoints.

## Supported Query Subset

- `PREFIX`
- `SELECT` and `SELECT DISTINCT`
- `LIMIT`
- `SERVICE <endpoint> { basic graph pattern }`

Unsupported features include local BGPs without `SERVICE`, `OPTIONAL`, `UNION`,
`FILTER`, `ORDER BY`, and `OFFSET`. Those are intentionally outside this first
example because the implementation models the RSA baseline after source
assignment, not a full SPARQL federation optimizer.
