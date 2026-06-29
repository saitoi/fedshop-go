# FedShop Go Code Walkthrough

This document walks through the current `go-engine` implementation by following
one `fedshop-go query` run from CLI arguments to FedShop artifacts. It is meant
to answer "what code actually runs?" rather than summarize the architecture.

The example is intentionally small, but every step maps to real implementation
files and tests in `go-engine`.

## Example Run

Assume FedShop calls the Go engine with a generated query and a batch endpoint
config:

```text
fedshop-go query
  --config target/config/config_batch0.ttl
  --query benchmark/generation/q01/instance_0/injected.sparql
  --out-result results.csv
  --out-source-selection source_selection.csv
  --query-plan query_plan.txt
  --stats engine_stats.json
  --selector ask
  --cache memory
  --planner source-count
  --join bind
  --max-concurrency 16
  --bind-batch-size 20
  --retry-count 2
```

For a minimal example, use this query:

```sparql
SELECT ?s ?label WHERE {
  ?s <http://example/p> ?label .
}
```

And this endpoint config:

```turtle
@prefix sd: <http://www.w3.org/ns/sparql-service-description#> .
<http://www.vendor0.fr/> a sd:Service ;
  sd:endpoint "http://localhost:8890/sparql?default-graph-uri=http%3A%2F%2Fwww.vendor0.fr%2F" .
<http://www.vendor1.fr/> a sd:Service ;
  sd:endpoint "http://localhost:8890/sparql?default-graph-uri=http%3A%2F%2Fwww.vendor1.fr%2F" .
```

The engine writes four output files:

```text
results.csv
source_selection.csv
query_plan.txt
engine_stats.json
```

## 1. Process Entry Point

The executable starts at:

```text
go-engine/cmd/fedshop-go/main.go
```

The whole file is deliberately tiny:

```go
func main() {
    os.Exit(cli.Run(os.Args[1:], os.Stdout, os.Stderr))
}
```

From there, all command dispatch goes through:

```text
go-engine/internal/cli/cli.go
```

The dispatch code:

```go
switch args[0] {
case "version":
    fmt.Fprintf(stdout, "fedshop-go %s\n", Version)
    return 0
case "completion":
    ...
case "query":
    return runQuery(ctx, args[1:], stderr)
case "summarize":
    return runSummary(ctx, args[1:], stderr)
default:
    return usageError(stderr, "unknown command "+strconv.Quote(args[0]))
}
```

For `query`, `runQuery` registers all benchmark flags and fills
`app.QueryOptions`:

```go
set.StringVar(&options.Config, "config", "", "Turtle endpoint config")
set.StringVar(&options.Query, "query", "", "SPARQL SELECT query")
set.StringVar(&options.OutResult, "out-result", "", "result CSV")
set.StringVar(&options.OutSources, "out-source-selection", "", "source-selection CSV")
set.StringVar(&options.OutPlan, "query-plan", "", "query plan")
set.StringVar(&options.OutStats, "stats", "", "JSON engine stats")
set.StringVar(&options.Selector, "selector", "ask", "broadcast, ask, or summary")
set.StringVar(&options.Join, "join", "hash", "hash or bind")
set.StringVar(&options.Planner, "planner", "source-count", "source-count or cost")
set.IntVar(&options.MaxConcurrency, "max-concurrency", 16, "maximum concurrent endpoint requests")
set.IntVar(&options.BindBatchSize, "bind-batch-size", 20, "VALUES rows per bound request")
```

Then it creates the endpoint HTTP client and transfers control to the app layer:

```go
httpClient, err := endpoint.NewHTTPClient(httpProxy)
...
client := endpoint.NewClient(httpClient, timeout, endpoint.WithRetries(retryCount))
if err := app.RunQuery(queryCtx, options, client); err != nil {
    fmt.Fprintf(stderr, "fedshop-go query: %v\n", err)
    return 1
}
```

Input to this step:

```text
CLI args
```

Output from this step:

```text
app.QueryOptions + endpoint.Client
```

## 2. App Orchestration

The main query orchestration is:

```text
go-engine/internal/app/query.go
```

`RunQuery` is the spine of the engine:

```go
queryInput, err := os.ReadFile(options.Query)
...
query, err := sparql.Parse(string(queryInput))
...
configInput, err := os.ReadFile(options.Config)
...
endpoints, err := federation.ParseEndpointConfig(string(configInput))
...
selection, selectionStats, err := selector.Select(ctx, query, endpoints)
...
order := planner.SourceCountOrder(query, selection)
if options.Planner == "cost" {
    order = planner.CostOrder(query, selection, catalog)
}
...
rows, executionStats, err = executor.New(protocol, executor.Options{...}).Execute(ctx, query, selection)
...
return artifact.WriteRun(..., query, rows, selection, stats)
```

The app layer does not know SPARQL details, HTTP payload syntax, join logic, or
CSV formatting. It connects packages and records phase timings:

```go
artifact.RunStats{
    Engine: "fedshop-go",
    Rows: len(rows),
    Selector: options.Selector,
    Join: options.Join,
    Planner: options.Planner,
    ASK: selectionStats.ASKRequests,
    CacheHits: selectionStats.CacheHits,
    HTTPRequests: int(protocol.Requests()),
    DataTransfer: protocol.Bytes(),
    ParseSeconds: parseSeconds,
    SourceSelectionSeconds: selectionSeconds,
    PlanningSeconds: planningSeconds,
    ExecutionSeconds: executionSeconds,
    TotalSeconds: time.Since(started).Seconds(),
    Partial: executionStats.Partial,
    FailedEndpoints: executionStats.FailedEndpoints,
    TripleOrder: order,
}
```

Input to this step:

```text
QueryOptions
endpoint.Client implementing ASK + SELECT + counters
```

Output from this step:

```text
Parsed query
Parsed endpoints
Source selection
Triple order
Execution rows
RunStats
Four artifact files
```

## 3. Query Parsing

Parser code lives in:

```text
go-engine/internal/sparql/parser.go
```

The public entry point is:

```go
func Parse(input string) (Query, error)
```

The parser first strips comments and rejects unsupported features:

```go
clean := stripComments(input)
if regexp.MustCompile(`(?i)\b(GRAPH|SERVICE|BIND|VALUES|MINUS|GROUP\s+BY|HAVING)\b`).MatchString(clean) {
    return Query{}, fmt.Errorf("parse query: unsupported graph-pattern feature")
}
```

Then it extracts prefixes, `SELECT`, the root graph pattern, order, offset, and
limit. The output is a compact FedShop-specific algebra:

```go
type Query struct {
    Prefixes map[string]string
    Select   []string
    Distinct bool
    Where    *Group
    OrderBy  []OrderCondition
    Offset   int
    Limit    int
}

type Group struct {
    Triples   []TriplePattern
    Filters   []string
    Optionals []*Group
    Unions    [][2]*Group
}

type TriplePattern struct {
    ID                         int
    Subject, Predicate, Object Term
}
```

For this input:

```sparql
SELECT ?s ?label WHERE {
  ?s <http://example/p> ?label .
}
```

The parsed shape is effectively:

```text
Query{
  Select: ["s", "label"],
  Distinct: false,
  Limit: -1,
  Where.Triples: [
    tp0: ?s <http://example/p> ?label
  ]
}
```

That `tp0` ID is the key used later by source selection, planning, execution,
and artifact writing.

## 4. Endpoint Config Parsing

Endpoint parsing lives in:

```text
go-engine/internal/federation/selector.go
```

The parser is intentionally narrow because FedShop emits a predictable service
description:

```go
var endpointPattern = regexp.MustCompile(`(?is)<([^>]+)>\s+a\s+sd:Service\s*;.*?sd:endpoint\s+"([^"]+)"`)

func ParseEndpointConfig(input string) ([]Endpoint, error) {
    matches := endpointPattern.FindAllStringSubmatch(input, -1)
    ...
    result = append(result, Endpoint{
        ID: endpointID(match[1]),
        GraphIRI: match[1],
        URL: match[2],
    })
}
```

For:

```turtle
<http://www.vendor0.fr/> a sd:Service ; sd:endpoint "http://proxy/vendor0" .
<http://www.ratingsite0.fr/> a sd:Service ; sd:endpoint "http://proxy/rating0" .
```

The resulting endpoints look like:

```text
[
  {
    ID: "http_www.vendor0.fr",
    GraphIRI: "http://www.vendor0.fr/",
    URL: "http://proxy/vendor0"
  },
  {
    ID: "http_www.ratingsite0.fr",
    GraphIRI: "http://www.ratingsite0.fr/",
    URL: "http://proxy/rating0"
  }
]
```

The endpoint `ID` is what appears in `source_selection.csv` and
`query_plan.txt`.

## 5. Source Selection

The source-selection interface is:

```go
type Selector interface {
    Select(context.Context, sparql.Query, []Endpoint) (Selection, SelectionStats, error)
}

type Selection map[int][]Endpoint
```

So the output is:

```text
triple ID -> selected endpoints
```

### Broadcast Selector

`BroadcastSelector` assigns every triple to every endpoint:

```go
func (BroadcastSelector) Select(_ context.Context, query sparql.Query, endpoints []Endpoint) (Selection, SelectionStats, error) {
    result := Selection{}
    for _, triple := range query.Triples() {
        result[triple.ID] = append([]Endpoint(nil), endpoints...)
    }
    return result, SelectionStats{}, nil
}
```

For one triple and two endpoints:

```text
selection[0] = [vendor0, vendor1]
```

### ASK Selector

`ASKSelector` performs FedX-style source selection. It creates one task for
each `(triple, endpoint)` pair, optionally deduplicates by cache key, and runs
bounded workers:

```go
for _, triple := range triples {
    for _, endpoint := range endpoints {
        key := selectionCacheKey(endpoint, triple, s.cache)
        if s.cache {
            if _, exists := tasksByKey[key]; exists {
                stats.CacheHits++
                continue
            }
        }
        tasksByKey[key] = askTask{triple: triple, endpoint: endpoint, key: key}
    }
}
...
has, err := s.client.Ask(workerCtx, task.endpoint, task.triple)
```

For `tp0 = ?s <http://example/p> ?label`, the HTTP layer receives:

```sparql
ASK WHERE { ?s <http://example/p> ?label . }
```

If vendor0 returns `true` and vendor1 returns `false`, source selection becomes:

```text
selection[0] = [vendor0]
stats.ASKRequests = 2
stats.CacheHits = 0
```

If the same triple text appears twice and cache is enabled, only one ASK per
endpoint is sent for that text.

### Summary Selector

Summary selection uses `internal/metadata`:

```go
func (s Selector) Select(_ context.Context, query sparql.Query, endpoints []federation.Endpoint) (federation.Selection, federation.SelectionStats, error) {
    selection := federation.Selection{}
    for _, triple := range query.Triples() {
        for _, endpoint := range endpoints {
            summary, known := s.Catalog.Endpoints[endpoint.ID]
            if triple.Predicate.Kind != sparql.TermIRI || !known {
                selection[triple.ID] = append(selection[triple.ID], endpoint)
                continue
            }
            if summary.Predicates[triple.Predicate.Value] > 0 {
                selection[triple.ID] = append(selection[triple.ID], endpoint)
            }
        }
    }
    return selection, federation.SelectionStats{}, nil
}
```

Example catalog:

```json
{
  "catalog": {
    "version": 1,
    "endpoints": {
      "vendor0": {
        "predicates": {
          "http://example/p": 12
        }
      },
      "vendor1": {
        "predicates": {}
      }
    }
  }
}
```

For `?s <http://example/p> ?label`, the selector keeps only `vendor0`.

## 6. Summary Construction

The summary command starts in `internal/app/summary.go` and delegates to
`internal/metadata/catalog.go`.

The query sent to every endpoint is:

```sparql
SELECT ?p (COUNT(*) AS ?count) WHERE { ?s ?p ?o } GROUP BY ?p
```

The builder runs those endpoint queries concurrently:

```go
catalog := Catalog{
    Version: 1,
    Fingerprint: fingerprint(endpoints),
    GeneratedAt: time.Now().UTC(),
    Endpoints: map[string]EndpointSummary{},
}
...
rows, err := querier.Query(ctx, endpoint, predicateSummaryQuery)
```

Example endpoint response rows:

```text
endpoint vendor0:
  p = http://example/p
  count = 12

endpoint vendor1:
  p = http://example/other
  count = 4
```

Example summary output:

```json
{
  "catalog": {
    "version": 1,
    "fingerprint": "sha256-of-endpoint-list",
    "generated_at": "2026-06-24T00:00:00Z",
    "endpoints": {
      "vendor0": {
        "predicates": {
          "http://example/p": 12
        }
      },
      "vendor1": {
        "predicates": {
          "http://example/other": 4
        }
      }
    }
  },
  "stats": {
    "build_seconds": 0.034,
    "http_requests": 2,
    "data_transfer": 100
  }
}
```

The summary build cost is recorded in the summary file, not mixed into one
query's `engine_stats.json`.

## 7. Planning

Planning lives in:

```text
go-engine/internal/planner/planner.go
```

There are two planning modes.

### Source Count

```go
func SourceCountOrder(query sparql.Query, selection federation.Selection) []int {
    triples := query.Triples()
    sort.SliceStable(triples, func(i, j int) bool {
        return len(selection[triples[i].ID]) < len(selection[triples[j].ID])
    })
    ...
}
```

Example:

```text
tp0 selected from 2 endpoints
tp1 selected from 1 endpoint

source-count order = [1, 0]
```

This means the engine starts with the more selective triple.

### Cost Order

Cost planning uses predicate counts from the summary catalog:

```go
func CostOrder(query sparql.Query, selection federation.Selection, catalog metadata.Catalog) []int {
    ...
    cost := estimate(triple, selection, catalog)
    connected := false
    for _, variable := range triple.Variables() {
        if chosen[variable] {
            connected = true
        }
    }
    if best < 0 || cost < bestCost || cost == bestCost && connected && !bestConnected {
        best = i
        bestCost = cost
        bestConnected = connected
    }
    ...
}
```

Example:

```sparql
SELECT ?s WHERE {
  ?s <http://example/common> ?x .
  ?x <http://example/rare> ?o .
  ?z <http://example/tiny> ?v .
}
```

With summary counts:

```text
common = 1000
rare = 10
tiny = 1
```

The planned order is:

```text
[tp2 tiny, tp1 rare, tp0 common]
```

This is a greedy order, not a full join-plan search.

## 8. Endpoint HTTP Requests

The SPARQL protocol code lives in:

```text
go-engine/internal/endpoint/client.go
```

### ASK

Source selection calls:

```go
func (c *Client) Ask(ctx context.Context, endpoint federation.Endpoint, triple sparql.TriplePattern) (bool, error) {
    query := "ASK WHERE { " + triple.Key() + " . }"
    body, err := c.do(ctx, endpoint.URL, query)
    ...
}
```

HTTP request body:

```text
query=ASK+WHERE+%7B+%3Fs+%3Chttp%3A%2F%2Fexample%2Fp%3E+%3Flabel+.+%7D
```

Endpoint JSON response:

```json
{"boolean": true}
```

Returned Go value:

```text
true
```

### SELECT

Execution calls:

```go
func (c *Client) Select(ctx context.Context, endpoint federation.Endpoint, triples []sparql.TriplePattern, inputs []executor.Binding) ([]executor.Binding, error) {
    query := buildSelect(triples, inputs)
    return c.Query(ctx, endpoint, query)
}
```

For an unbound first triple:

```sparql
SELECT * WHERE {
  ?s <http://example/p> ?label .
}
```

For a bound second triple, the engine sends only relevant bound variables:

```sparql
SELECT * WHERE {
  VALUES ( ?s ) {
    ( <http://example/s1> )
    ( <http://example/s2> )
  }
  ?s <http://example/label> ?label .
}
```

Endpoint JSON response:

```json
{
  "head": { "vars": ["s", "label"] },
  "results": {
    "bindings": [
      {
        "s": { "type": "uri", "value": "http://example/s1" },
        "label": { "type": "literal", "xml:lang": "en", "value": "Phone" }
      }
    ]
  }
}
```

Returned Go rows:

```text
[]executor.Binding{
  {
    "s":     IRI("http://example/s1"),
    "label": Literal("Phone", "", "en"),
  },
}
```

Numeric literals are normalized at this boundary. For example:

```text
"2787.7100000000000364"^^xsd:decimal -> "2787.71"
```

The client counts request attempts and response bytes for stats.

## 9. Execution

Execution code lives in:

```text
go-engine/internal/executor/executor.go
```

The public entry point is:

```go
func (e *Executor) Execute(ctx context.Context, query sparql.Query, selection federation.Selection) ([]Binding, Stats, error)
```

The rough execution flow:

```go
rows, stats, err := e.executeGroup(ctx, query.Where, selection, nil, outputVars)
...
projected := make([]Binding, 0, len(rows))
...
if query.Distinct {
    projected = distinct(projected, query.Select)
}
if len(query.OrderBy) > 0 {
    sort.SliceStable(projected, ...)
}
...
return projected[start:end], stats, nil
```

Inside `executeGroup`:

```go
rows := cloneBindings(inputs)
if len(rows) == 0 {
    rows = []Binding{{}}
}
...
for i := 0; i < len(remaining); i++ {
    triple := remaining[i]
    sources := selection[triple.ID]
    union, s, err := e.fetchTriple(ctx, triple, sources, rows)
    ...
    rows = join(rows, union)
    ...
    pendingFilters, rows = applyEligibleFiltersScalar(pendingFilters, rows, scalarSets)
}
...
for _, pair := range group.Unions {
    left, ...
    right, ...
    rows = append(left, right...)
}
for _, optional := range group.Optionals {
    right, ...
    rows = leftJoin(rows, right)
}
```

### Simple Hash Join Example

Query:

```sparql
SELECT DISTINCT ?s ?price WHERE {
  ?s <http://example/product> ?p .
  ?p <http://example/price> ?price .
  FILTER(?price < 20)
}
ORDER BY DESC(?price)
OFFSET 1
LIMIT 1
```

Input rows returned by endpoints:

```text
tp0:
  {s: http://s1, p: http://p1}
  {s: http://s2, p: http://p2}
  {s: http://s3, p: http://p3}

tp1:
  {p: http://p1, price: 10}
  {p: http://p2, price: 15}
  {p: http://p3, price: 25}
```

Execution:

```text
join on p
-> {s: http://s1, p: http://p1, price: 10}
-> {s: http://s2, p: http://p2, price: 15}
-> {s: http://s3, p: http://p3, price: 25}

FILTER(?price < 20)
-> s1 price 10
-> s2 price 15

ORDER BY DESC(?price)
-> s2 price 15
-> s1 price 10

OFFSET 1 LIMIT 1
-> s1 price 10
```

Final projected rows:

```text
[{s: http://s1, price: 10}]
```

### Bind Join Example

Query:

```sparql
SELECT ?s ?o WHERE {
  ?s <http://example/first> ?x .
  ?x <http://example/second> ?o .
}
```

First request has no inputs:

```text
Select(endpoint one, [tp0], inputs=[])
-> {s: http://s, x: http://x}
```

Second request receives the intermediate binding:

```text
Select(endpoint two, [tp1], inputs=[{s: http://s, x: http://x}])
```

Generated remote query shape:

```sparql
SELECT * WHERE {
  VALUES ( ?x ) {
    ( <http://x> )
  }
  ?x <http://example/second> ?o .
}
```

Remote result:

```text
{x: http://x, o: http://o}
```

Joined final row:

```text
{s: http://s, x: http://x, o: http://o}
```

Projected CSV row:

```text
http://s,http://o
```

### OPTIONAL Example

Query:

```sparql
SELECT ?s ?label WHERE {
  ?s <http://example/p> ?o .
  OPTIONAL { ?s <http://example/label> ?label }
}
```

Base rows:

```text
{s: http://s1}
{s: http://s2}
```

Optional rows:

```text
{s: http://s1, label: "one"}
```

Left-join result:

```text
{s: http://s1, label: "one"}
{s: http://s2, label: unbound}
```

This matters for FedShop because optional groups must receive the incoming
bindings from the outer group. In bind mode, that means optional remote requests
are constrained by the current rows.

### UNION Example

Query:

```sparql
SELECT ?s ?value WHERE {
  ?s <http://example/base> ?o .
  { ?s <http://example/left> ?value }
  UNION
  { ?s <http://example/right> ?value }
}
```

After base rows are fetched, each union arm is evaluated with those incoming
bindings. The final rows are the concatenation of left-arm and right-arm
results.

## 10. Fetching Triples

The executor fetches each triple through:

```go
func (e *Executor) fetchTriple(ctx context.Context, triple sparql.TriplePattern, sources []federation.Endpoint, rows []Binding) ([]Binding, Stats, error)
```

In `hash` mode:

```text
inputs are nil unless this is an exclusive group
each selected endpoint receives a plain SELECT for the triple
results are unioned and deduplicated
```

In `bind` mode:

```text
current rows become VALUES input
rows are chunked by --bind-batch-size
endpoint requests are bounded by --max-concurrency
```

The locality routing optimization reduces fan-out when a binding value already
reveals which endpoint owns it. Example:

```text
endpoint vendor0 graph IRI: http://www.vendor0.fr/
endpoint vendor1 graph IRI: http://www.vendor1.fr/

current binding:
  ?s = http://www.vendor0.fr/Product1

next triple:
  ?s <http://example/label> ?label
```

The request is sent only to `vendor0`, not both endpoints.

## 11. Exclusive Groups

Exclusive grouping reduces request count when selected triples all belong to
one endpoint.

Query:

```sparql
SELECT ?s ?o WHERE {
  ?s <http://example/first> ?x .
  ?x <http://example/second> ?o .
}
```

Selection:

```text
tp0 -> [one]
tp1 -> [one]
```

With `--exclusive-groups` and `--join hash`, the executor sends one request:

```text
Select(endpoint one, [tp0, tp1], inputs=[])
```

Instead of:

```text
Select(endpoint one, [tp0], inputs=[])
Select(endpoint one, [tp1], inputs=[])
local join
```

This is why the test `TestExclusiveGroupUsesOneRequest` expects
`HTTPRequests == 1`.

Post-bind exclusive grouping is similar, but it triggers after earlier joins
make endpoint ownership visible from current bindings.

## 12. Filter Optimizations

FedShop templates can produce large intermediate products before filters remove
most rows. The executor has targeted optimizations for that shape.

### Eager Filter Application

Filters start in a pending list:

```go
pendingFilters := append([]string(nil), group.Filters...)
```

After each join, filters whose variables are available are applied:

```go
pendingFilters, rows = applyEligibleFiltersScalar(pendingFilters, rows, scalarSets)
```

So a filter like:

```sparql
FILTER(?price < 20)
```

can run immediately after `?price` is bound, before later triples add more
rows.

### Scalar-Set Optimization

Some triples introduce variables used only in filters, not in output and not in
later joins.

Example shape:

```sparql
SELECT ?other WHERE {
  ?anchor <http://example/sameAs> <http://example/Ref> .
  ?anchor <http://example/p1> ?filterVar1 .
  ?other  <http://example/p1> ?simVar1 .
  FILTER(?simVar1 > ?filterVar1 - 10 && ?simVar1 < ?filterVar1 + 10)
}
```

Instead of joining every `?filterVar1` value into the row stream, the executor
collects those values as a scalar set:

```text
scalarSets["filterVar1"] = [100, 200]
```

Then later rows for `?simVar1` are tested against that set. This avoids a
cross-product whose only purpose is filter evaluation.

### Filter-Group Optimization

For consecutive triples with the same bound subject and filter-only variables,
the executor can fetch each triple independently and keep only subjects that
pass all relevant filter checks. This avoids materializing:

```text
property1 values x property2 values x property3 values
```

when the final result only needs to know whether a subject passes the filter.

## 13. Artifact Writing

Artifact code lives in:

```text
go-engine/internal/artifact/writer.go
```

The app calls:

```go
artifact.WriteRun(paths, query, rows, selection, stats)
```

It writes four files.

### results.csv

Input:

```text
query.Select = ["s", "label"]
rows = [
  {s: IRI("http://s"), label: PlainLiteral("Phone")}
]
```

Output:

```csv
s,label
http://s,Phone
```

### source_selection.csv

Input:

```text
tp0 = ?s <http://example/p> ?label
selection[0] = [endpoint_one]
```

Output:

```csv
triple,source_selection
?s <http://example/p> ?label,"[""endpoint_one""]"
```

### query_plan.txt

Input:

```text
selector = ask
planner = source-count
join = bind
triple_order = [0]
selection[0] has one source
```

Output:

```text
fedshop-go plan
selector=ask
planner=source-count
join=bind
triple_order=[0]

tp0: ExclusiveStatement: ?s <http://example/p> ?label
  sources: endpoint_one
```

Classification rules:

```text
0 sources -> EmptyStatementPattern
1 source  -> ExclusiveStatement
2+ sources -> StatementSourcePattern
```

### engine_stats.json

Example:

```json
{
  "engine": "fedshop-go",
  "rows": 1,
  "selector": "ask",
  "join": "bind",
  "planner": "source-count",
  "ask": 2,
  "cache_hits": 0,
  "http_requests": 3,
  "data_transfer": 220,
  "parse_seconds": 0.0002,
  "source_selection_seconds": 0.0101,
  "planning_seconds": 0.00001,
  "execution_seconds": 0.0304,
  "total_seconds": 0.041,
  "partial": false,
  "triple_order": [0],
  "generated_at": "2026-06-24T00:00:00Z"
}
```

The exact timings and byte counts vary per run.

## 14. End-to-End Mini Trace

For the example query:

```sparql
SELECT ?s ?label WHERE {
  ?s <http://example/p> ?label .
}
```

With two endpoints:

```text
vendor0 -> ASK true
vendor1 -> ASK false
```

The real package flow is:

```text
cli.Run
-> cli.runQuery
-> endpoint.NewHTTPClient
-> endpoint.NewClient
-> app.RunQuery
   -> os.ReadFile(query)
   -> sparql.Parse
      -> Query{Select:["s","label"], Where.Triples:[tp0]}
   -> os.ReadFile(config)
   -> federation.ParseEndpointConfig
      -> []Endpoint{vendor0, vendor1}
   -> federation.NewASKSelector(...).Select
      -> endpoint.Client.Ask(vendor0, tp0) = true
      -> endpoint.Client.Ask(vendor1, tp0) = false
      -> Selection{0: [vendor0]}
   -> planner.SourceCountOrder
      -> [0]
   -> executor.New(...).Execute
      -> fetchTriple(tp0, [vendor0], [{}])
      -> endpoint.Client.Select(vendor0, [tp0], nil)
      -> []Binding{{s:http://s, label:"Phone"}}
      -> project ["s","label"]
   -> artifact.WriteRun
      -> results.csv
      -> source_selection.csv
      -> query_plan.txt
      -> engine_stats.json
```

Final result file:

```csv
s,label
http://s,Phone
```

Final source-selection file:

```csv
triple,source_selection
?s <http://example/p> ?label,"[""vendor0""]"
```

Final plan:

```text
fedshop-go plan
selector=ask
planner=source-count
join=bind
triple_order=[0]

tp0: ExclusiveStatement: ?s <http://example/p> ?label
  sources: vendor0
```

## 15. Where To Read Next

Read the implementation in this order:

1. `go-engine/internal/app/query.go`
2. `go-engine/internal/sparql/parser.go`
3. `go-engine/internal/federation/selector.go`
4. `go-engine/internal/endpoint/client.go`
5. `go-engine/internal/planner/planner.go`
6. `go-engine/internal/executor/executor.go`
7. `go-engine/internal/executor/expression.go`
8. `go-engine/internal/artifact/writer.go`

The tests are useful because they show executable examples:

- `go-engine/internal/app/query_test.go`: full fake-protocol run.
- `go-engine/internal/federation/selector_test.go`: endpoint parsing and ASK cache.
- `go-engine/internal/metadata/catalog_test.go`: summary build and summary selector.
- `go-engine/internal/planner/planner_test.go`: source-count and cost ordering.
- `go-engine/internal/endpoint/client_test.go`: HTTP request/response boundaries.
- `go-engine/internal/executor/executor_test.go`: joins, optionals, unions, exclusive groups, locality routing, scalar filters.
- `go-engine/internal/artifact/writer_test.go`: final file shapes.
