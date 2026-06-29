# FedShop Go Engine: Architecture and Reference-Engine Comparison

## Executive Summary

`fedshop-go` is a standalone federated SPARQL engine built specifically for
the FedShop benchmark. It does not embed RDF4J, Jena, FedX, or another query
engine. The implementation owns the full runtime path:

```text
FedShop adapter
-> fedshop-go CLI
-> endpoint config + query parser
-> source selector
-> triple-order planner
-> federated executor
-> FedShop-compatible artifacts
```

The engine is intentionally narrower than the reference systems. It supports
the SPARQL surface exercised by the twelve FedShop BSBM templates and exposes
only the controls needed to benchmark source selection, planning, join strategy,
and endpoint behavior. That small scope is its main design advantage: each
phase is testable as ordinary Go code, and the engine emits native FedShop
results, source-selection files, query plans, and JSON statistics without
screen-scraping a larger runtime.

The current implementation is closest to FedX in behavior: runtime source
selection, exclusive-source recognition, batched bound requests, and local
joins. It also includes a first-layer CostFed/SPLENDID/Semagrow-style metadata
path through predicate summaries and greedy cost ordering. It does not yet
implement full join-cardinality estimation, dynamic-programming plan search,
or adaptive non-blocking execution.

## Command Surface

The binary entry point is `go-engine/cmd/fedshop-go`. The CLI is deliberately
non-interactive and has two benchmark-relevant commands.

`query` executes or plans one FedShop query:

```text
fedshop-go query
  --config target/config/config_batch0.ttl
  --query injected.sparql
  --out-result results.csv
  --out-source-selection source_selection.csv
  --query-plan query_plan.txt
  --stats engine_stats.json
  --selector ask|summary|broadcast
  --summary target/summary/summary_batch0.json
  --cache memory|off
  --planner source-count|cost
  --join hash|bind
  --exclusive-groups
  --post-bind-max-input-rows N
  --max-concurrency N
  --bind-batch-size N
  --timeout DURATION
  --retry-count N
  --failure-policy strict|partial
  --http-proxy URL
  --noexec
```

`summarize` builds a predicate-cardinality catalog for a FedShop endpoint
configuration:

```text
fedshop-go summarize
  --config target/config/config_batch0.ttl
  --output target/summary/summary_batch0.json
  --max-concurrency N
  --timeout DURATION
```

The `--noexec` mode is important for source-assignment experiments: it parses,
selects sources, plans, and emits artifacts without issuing SELECT requests.

## Package Design

The engine is organized as small internal packages with clear ownership.

| Package | Responsibility |
|---|---|
| `internal/cli` | Command parsing, defaults, process exit codes, shell completions. |
| `internal/app` | Orchestration for query and summary commands. |
| `internal/sparql` | FedShop-oriented SELECT parser and compact query algebra. |
| `internal/federation` | Endpoint config parsing, source selector interfaces, ASK and broadcast selectors. |
| `internal/metadata` | Predicate summary construction, storage, fingerprinting, and summary selector. |
| `internal/planner` | Triple ordering by source count or predicate-cardinality estimate. |
| `internal/endpoint` | SPARQL HTTP protocol, proxy support, retries, counters, and JSON decoding. |
| `internal/executor` | Federated execution, hash/bind joins, OPTIONAL, UNION, filters, projection, ordering, slicing. |
| `internal/artifact` | Deterministic result, source-selection, plan, and stats writers. |

The module currently has no third-party engine dependency. `go.mod` only
declares the local module and Go version, so reference-engine behavior is reused
as design, not as linked code.

## Query Model

The parser supports the FedShop template subset:

- `SELECT` and `SELECT DISTINCT`
- BGP triple patterns
- binary `UNION` groups
- correlated `OPTIONAL` groups
- `FILTER` expressions used by the templates
- `ORDER BY`, `OFFSET`, and `LIMIT`
- prefixes, IRIs, variables, and literals needed for generated queries

The parser rejects unsupported graph-pattern features such as `GRAPH`,
`SERVICE`, `BIND`, `VALUES`, `MINUS`, `GROUP BY`, and `HAVING`. This is an
intentional boundary: FedShop's normal engine inputs are raw generated
`injected.sparql` SELECT queries, not pre-decomposed SERVICE plans.

The internal algebra is compact:

- `Query` stores prefixes, selected variables, distinct flag, root group,
  order conditions, offset, and limit.
- `Group` stores triples, filters, optionals, and binary union arms.
- `TriplePattern` receives a stable integer ID and can render a
  composition-compatible key.

Stable triple IDs are reused across selection, planning, execution, source
selection output, and plan output.

## Endpoint Model

FedShop produces Turtle service descriptions. `fedshop-go` parses entries of
the form:

```text
<graphIRI> a sd:Service ; ... sd:endpoint "endpointURL"
```

Each member becomes:

- `ID`: sanitized endpoint identifier used in artifacts
- `GraphIRI`: source graph identity
- `URL`: SPARQL endpoint URL

Correct graph scoping is required. Each endpoint URL must isolate the intended
graph, for example with `default-graph-uri`. URL paths alone are not enough for
the local Virtuoso setup because named-graph routing can otherwise expose the
same graph through every member, inflating source assignments and result counts.

## Source Selection

Source selection produces a map from triple-pattern ID to candidate endpoints.
Three selectors are implemented.

| Selector | Behavior | Intended Use |
|---|---|---|
| `broadcast` | Assigns every triple to every endpoint. | Baseline and debugging. |
| `ask` | Sends SPARQL `ASK WHERE { triple }` to candidate endpoints. | FedX-like correctness baseline. |
| `summary` | Uses predicate summaries to keep endpoints where the predicate is present. | Metadata experiment and lower request count. |

The ASK selector uses bounded workers and a query-local cache. The cache key is
the endpoint plus the canonical triple pattern. When cache is off, the triple ID
is included so duplicate triple text does not collapse. Cache reuse is only
within a single process/query, matching the benchmark expectation that each run
starts cold.

The summary selector is deliberately conservative. If a predicate is not a fixed
IRI, or an endpoint is missing from the catalog, the endpoint remains a
candidate. This avoids pruning valid sources when metadata is incomplete.

## Metadata Catalog

The summary command queries each endpoint with:

```sparql
SELECT ?p (COUNT(*) AS ?count) WHERE { ?s ?p ?o } GROUP BY ?p
```

It writes a versioned JSON payload containing:

- catalog version
- federation fingerprint
- generation timestamp
- per-endpoint predicate counts
- separately measured build seconds, HTTP request count, and transfer bytes

The fingerprint is derived from endpoint ID, graph IRI, and URL. Summary build
cost is intentionally separated from per-query cost so benchmark results can
distinguish amortized metadata construction from query execution.

This catalog is less expressive than CostFed, Semagrow, or SPLENDID metadata:
it knows predicate presence and predicate cardinality only. It does not yet
capture subject/object distinct counts, join-variable selectivity, endpoint
latency, transfer cost, or pairwise join cardinalities.

## Planning

Planning currently returns an ordered list of triple IDs, not a full physical
operator tree.

`source-count` planning sorts triples by increasing number of selected sources.
This is the default because it is robust with both ASK and summary selection.

`cost` planning requires `--selector summary --summary ...`. It greedily picks
the next triple with the lowest sum of selected-endpoint predicate counts. When
costs tie, triples connected to already chosen variables are preferred.

This is a useful first approximation, but it is not a global optimizer. It does
not enumerate bushy plans, estimate joins, choose remote-vs-local operators, or
compare network transfer costs.

## Endpoint Protocol

`internal/endpoint` uses SPARQL over HTTP POST with
`application/x-www-form-urlencoded` query bodies and
`application/sparql-results+json` responses.

Implemented protocol behavior:

- optional explicit HTTP proxy for FedShop's measurement proxy
- per-command context timeout and per-request timeout
- retry support for transient transport failures and HTTP 502, 503, and 504
- completed request-attempt counter
- response-body byte counter
- numeric lexical canonicalization for decimal, double, and float values

ASK requests are generated as:

```sparql
ASK WHERE { <triple pattern> . }
```

SELECT requests are generated as:

```sparql
SELECT * WHERE {
  VALUES (...) { ... }
  <triple pattern> .
}
```

The `VALUES` block is included only for variables that both appear in the
remote triple group and are already bound in the current input rows. Input rows
are deduplicated by that relevant variable subset before the request is sent.

## Execution Model

The executor evaluates one parsed query group against the source assignment.
The high-level order is:

1. Start with one empty binding or the incoming bindings for nested groups.
2. Order group triples using planner output.
3. Fetch each triple from selected sources.
4. Join fetched rows into the current bindings.
5. Apply eligible filters as soon as their variables are available.
6. Evaluate `UNION` arms with incoming bindings.
7. Evaluate `OPTIONAL` groups with incoming bindings and left-join the result.
8. Apply remaining filters.
9. Project selected variables.
10. Apply `DISTINCT`, `ORDER BY`, `OFFSET`, and `LIMIT`.

Nested `UNION` and `OPTIONAL` groups receive incoming bindings. This is required
for correct correlated optional evaluation and bind-join behavior.

## Physical Operators

Two join modes are exposed.

`hash` mode fetches triple results and joins them locally. The local join uses
shared variables as a hash key and builds the hash table on the smaller side.
If there are no shared variables, it falls back to compatibility/cross-product
joining.

`bind` mode sends current bindings to endpoints as batched `VALUES` requests.
The batch size is controlled by `--bind-batch-size`. Bind inputs are partitioned
by endpoint when a bound subject or object value reveals the endpoint identity;
remaining rows are broadcast to the selected sources.

For both modes, endpoint fetches are scheduled with concurrency bounded by
`--max-concurrency`. Results are sorted/deduplicated where needed to keep
artifact output deterministic.

## Source Grouping Optimizations

`fedshop-go` has two exclusive-source optimizations.

Pre-bind exclusive group:

- If every triple in a group has exactly one selected endpoint and that endpoint
  is the same for all triples, the executor can send the whole group as one
  remote SELECT.
- This path is guarded by `--exclusive-groups`.

Post-bind exclusive group:

- After a join, the executor checks whether all remaining triples can be routed
  to the same endpoint using the current bound subject values.
- If so, it sends those remaining triples as one remote SELECT with the current
  bindings.
- `--post-bind-max-input-rows` can disable this optimization above a row-count
  threshold.

These optimizations are FedX-like in spirit: move coherent source-local work to
the endpoint and avoid joining several single-source properties in memory.

## Filter Optimizations

The executor includes FedShop-specific handling for filter-heavy product
queries.

Eager filters:

- Filters are held in a pending list.
- After each join, any filter whose variables are all available is applied.
- This prunes rows before later remote requests and joins.

Scalar-set optimization:

- If a triple introduces variables used only by filters and those variables do
  not need to appear in the final output, the executor can collect their values
  as scalar sets instead of joining them into the row stream.
- This avoids multiplying rows only to evaluate scalar comparisons later.

Filter-group optimization:

- Consecutive triples with the same bound subject and filter-only variables can
  be fetched and evaluated independently.
- The executor keeps subjects that pass all relevant filter checks rather than
  materializing the product of all property values.

These optimizations are narrower than a general relational optimizer, but they
target a real FedShop pain point: generated templates can produce very large
intermediate cross products before filters reduce the result.

## Failure Handling

The executor supports two failure policies.

`strict` is the default. Endpoint errors fail the query.

`partial` records failed endpoints, marks the run partial, and continues where
the affected operation allows it. Partial runs are visible in `engine_stats.json`
and should not be treated as equivalent to a clean result unless the benchmark
analysis explicitly allows partial execution.

Request retries are handled below the executor by the endpoint client and are
bounded by the command context.

## FedShop Artifacts

`internal/artifact` writes all benchmark-facing outputs directly.

| Artifact | Contents |
|---|---|
| result CSV | Header from selected variables, then projected lexical values. |
| source-selection CSV | Triple key plus JSON list of selected endpoint IDs. |
| query plan | Selector, planner, join mode, triple order, and statement-source classification. |
| stats JSON | Rows, selector, join, planner, ASK/cache counts, HTTP requests, bytes, phase timings, partial status, failed endpoints, triple order. |

Plan output classifies each triple as:

- `EmptyStatementPattern` when no sources are selected
- `ExclusiveStatement` when exactly one source is selected
- `StatementSourcePattern` when multiple sources are selected

This mirrors the source-selection concepts used by FedX while keeping the
artifact format simple and deterministic.

## Capability Matrix

| Area | fedshop-go | FedX | CostFed / Hibiscus | Semagrow | SPLENDID | ANAPSID | FedUP / RSA |
|---|---|---|---|---|---|---|---|
| Scope | Purpose-built FedShop engine | General RDF4J federation | FedX-derived system with summaries/costing | General federated RDF4J-style optimizer | Metadata-heavy federated optimizer | Adaptive federated SPARQL engine | Source-assignment and SERVICE-plan baseline |
| Query model | Native FedShop SELECT subset | RDF4J algebra | FedX/RDF4J extensions | Query blocks and physical plans | Sesame/RDF4J algebra | Custom operators | Jena algebra / FedQPL / SERVICE |
| Source selection | ASK, broadcast, or predicate summary | ASK with source-selection cache | TBSS/Hibiscus summaries plus ASK refinement | Metadata-driven selectors | ASK or VoID statistics | Endpoint descriptions and runtime behavior | Summary-derived assignments |
| Metadata | Predicate count per endpoint | Endpoint statistics and cache | Triple/join summaries, costs | Cardinality/cost metadata | VoID/SPLENDID statistics | Runtime/operator state | Summary knowledge outside executor |
| Planning | Greedy source-count or predicate-count order | Statement grouping and FedX optimizer | Cost-based join ordering | Physical-plan enumeration | Dynamic-programming plan search | Adaptive operator choice | FedQPL rewrites; backend executes |
| Physical joins | Hash join, batched VALUES bind join, left join | Worker/bind/bound joins | FedX operators plus extensions | Bind, hash, merge, remote, left joins | Bind and hash joins | Symmetric/nested hash, XJoin family | Jena/FedX physical operators |
| Source grouping | Pre-bind and post-bind exclusive groups | Exclusive statements and exclusive groups | FedX grouping plus CostFed selectors | Remote source-query plans | Remote subqueries | Runtime decomposition | SERVICE groups and factorization |
| Concurrency | Bounded ASK and SELECT workers | Controlled worker scheduler | FedX concurrency substrate | Parallel evaluation infrastructure | Runtime cursors | Pipelined/non-blocking operators | Delegated to backend |
| Failure policy | Strict or explicit partial mode; transient retries | Federation error handling | Inherits/extends FedX behavior | RDF4J evaluation errors | Sesame evaluation errors | Designed for delayed sources | SERVICE/SERVICE SILENT semantics |
| FedShop output | Native artifacts and stats | Python adapter parses output | Python adapters plus summary files | Python adapter | Python adapter | Python adapter | Emits SERVICE plans/results via backend |

## Reference-Engine Comparison

### FedX

FedX is the nearest execution reference. Both systems perform runtime source
selection, classify triple patterns by selected source count, recognize
exclusive work, and use bound requests to reduce transferred data.

`fedshop-go` reimplements those contracts with smaller Go data structures:
`Selection` is a map from triple ID to endpoints, plan output names
`ExclusiveStatement` and `StatementSourcePattern`, and bind execution uses
SPARQL `VALUES` blocks.

FedX remains more mature in scheduler design and integration. Its controlled
worker scheduler and RDF4J algebra optimizer cover a broader SPARQL surface.
`fedshop-go` has bounded request concurrency and deterministic assembly, but it
does not maintain a federation-wide source-selection cache or a general RDF4J
operator tree.

### CostFed and Hibiscus

CostFed and Hibiscus are the main references for moving beyond ASK-everywhere.
They use richer summaries and cost models to reduce probes and choose better
plans.

`fedshop-go` currently implements only the first step in that direction:
predicate presence/cardinality summaries and greedy predicate-count ordering.
It cannot yet estimate complete join trees, bound-variable selectivity, network
transfer, or top-k variants.

### Semagrow

Semagrow separates logical source assignment from candidate physical plans and
can choose among bind, hash, merge, remote, and left joins.

`fedshop-go` has a simpler separation: selector output is independent from
planner output, but the planner returns only a triple order. The next useful
Semagrow-inspired improvement would be explicit logical and physical plan nodes
so the engine can compare remote group execution, hash join, and bind join as
operator choices instead of CLI modes.

### SPLENDID

SPLENDID is the stronger reference for VoID/statistics-based optimization and
dynamic-programming search over equivalent plans.

`fedshop-go` does not attempt SPLENDID-style enumeration. Its current filter
placement is opportunistic and runtime-driven: apply filters when variables are
available and avoid filter-only cross products. That is less general than
SPLENDID planning, but it is effective for known FedShop template shapes.

### ANAPSID

ANAPSID focuses on adaptive, non-blocking execution under heterogeneous endpoint
latency. Its XJoin-family operators can continue producing results while some
sources are slow.

`fedshop-go` is deterministic and blocking at the current operator level. It
uses contexts, timeouts, bounded concurrency, and retries to cap stalls, but it
does not implement adaptive scheduling, mid-query reordering, or non-blocking
partial-result operators.

### FedUP and RSA

FedUP and RSA are source-assignment and SERVICE-plan references. They exploit
summary knowledge to construct decomposed plans and then delegate physical
execution to Jena or FedX.

`fedshop-go` differs by owning physical execution. Its `--noexec` mode is the
bridge for fair source-assignment analysis: it can emit selected sources and a
plan without mixing in endpoint SELECT time.

## Current Limits

The implementation is intentionally not a full SPARQL engine.

- Unsupported SPARQL features include `SERVICE`, `GRAPH`, `BIND`, explicit
  input `VALUES`, `MINUS`, aggregation, `GROUP BY`, and `HAVING`.
- Summary metadata is predicate-level only.
- Cost planning is greedy and left-deep.
- Execution does not adapt to endpoint latency beyond timeout/retry behavior.
- Query-wide cache state is not persisted across benchmark attempts.
- The result model writes lexical CSV values and relies on benchmark comparison
  logic for equivalence.

## Prioritized Roadmap

1. Keep result equivalence and artifact validity as release gates for all 12
   templates before expanding optimizer behavior.
2. Extend summaries with subject/object distinct counts and join-variable
   selectivity.
3. Introduce explicit logical and physical plan nodes, then choose between
   remote exclusive groups, hash joins, and bind joins per subplan.
4. Add transfer-aware and cardinality-aware cost estimates before replacing
   greedy ordering.
5. Add adaptive scheduling only after stable request, byte, and latency metrics
   make slow-source behavior measurable.
6. Preserve deterministic artifacts and `--noexec` source-assignment mode as
   compatibility gates for every optimization.
