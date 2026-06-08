# FedX Data Structures And Algorithms

This guide explains FedX from a data-structure point of view. It is meant to
answer: what objects exist during query execution, how they change, and which
algorithm connects source selection to execution.

The concrete files to keep open while reading are:

- `reference-repos/FedShop/fedshop/engines/fedx.py`
- `reference-repos/fedshop-forks/FedX/src/main/java/org/example/FedX.java`
- `reference-repos/fedshop-forks/FedX/src/main/java/org/example/FedXContainer.java`
- `reference-repos/fedshop-forks/FedX/src/main/java/org/eclipse/rdf4j/federated/optimizer/SourceSelection.java`
- `reference-repos/fedshop-forks/FedX/src/main/java/org/eclipse/rdf4j/federated/evaluation/SparqlTripleSource.java`

## Big Picture

FedX starts with two inputs:

```text
SPARQL query text
federation member config
```

It turns them into these runtime structures:

```text
query text
-> parsed RDF4J algebra tree
-> list of statement patterns
-> map from statement pattern to selected endpoints
-> rewritten algebra tree with source annotations
-> endpoint subqueries
-> binding streams
-> final joined bindings
```

The core transformation is:

```text
triple pattern + endpoints
-> selected endpoint list
-> algebra node that knows where to execute
```

## Important Data Structures

### Endpoint

An `Endpoint` represents one federation member.

For FedShop, a federation member is a virtual SPARQL endpoint backed by
Virtuoso and routed through the FedShop proxy.

Important endpoint data:

```text
endpoint id
endpoint URL
endpoint config
triple source
repository connection
```

The endpoint list comes from the generated FedX Turtle config:

```text
target/config/config_batch{batch_id}.ttl
```

FedShop writes this file in `fedx.py` using `generate_config_file`.

### StatementPattern

A `StatementPattern` is RDF4J's algebra representation of a SPARQL triple
pattern.

Example query:

```sparql
SELECT ?product ?label WHERE {
  ?product a ?type .
  ?product rdfs:label ?label .
}
```

RDF4J turns this into statement patterns like:

```text
StatementPattern(?product, rdf:type, ?type)
StatementPattern(?product, rdfs:label, ?label)
```

FedX source selection works mostly over a list of these objects:

```java
List<StatementPattern> stmts
```

### SubQuery

FedX wraps a statement pattern into a `SubQuery` when checking the cache:

```text
SubQuery(statement pattern, dataset)
```

This is the cache key for source-selection knowledge.

It means:

```text
For this triple pattern, under this dataset/default graph context,
what do we know about endpoint E?
```

QUESTION: What do you mean by 'what do we know about endpoint E'? How is endpoint E being passed in SubQuery(...)

### SourceSelectionCache

The source-selection cache stores what FedX already knows about endpoint
coverage.

For a pair:

```text
SubQuery + Endpoint
```

the cache returns a `StatementSourceAssurance`:

```text
HAS_REMOTE_STATEMENTS
POSSIBLY_HAS_STATEMENTS
NONE
```

Meaning:

- `HAS_REMOTE_STATEMENTS`: use this endpoint without another remote check.
- `POSSIBLY_HAS_STATEMENTS`: ask the endpoint.
- `NONE`: skip this endpoint.

### StatementSource

A `StatementSource` is the selected source for a statement pattern.

It stores:

```text
endpoint id
source type
```

In this FedShop setup, the source type is usually remote:

```java
StatementSourceType.REMOTE
```

### stmtToSources

This is the central source-selection result:

```java
Map<StatementPattern, List<StatementSource>> stmtToSources
```

Read it as:

```text
for this triple pattern,
these endpoints may produce matching triples
```

Example:

```text
tp1 -> [shop001, shop017]
tp2 -> [shop017, review004, review009]
```

This map is built in `SourceSelection.java` and copied to
`FedX.CONTAINER` so FedShop can write provenance/source-selection output.

### Algebra Nodes After Source Selection

After source selection, FedX rewrites each original `StatementPattern`.

There are three outcomes:

```text
0 sources -> EmptyStatementPattern
1 source  -> ExclusiveStatement
N sources -> StatementSourcePattern
```

These are the execution-oriented data structures.

#### EmptyStatementPattern

No endpoint can answer this triple pattern.

The query branch can often be pruned because it cannot produce results.

#### ExclusiveStatement

Exactly one endpoint can answer this triple pattern.

This is the best case:

```text
send this triple pattern only to endpoint E
```

#### StatementSourcePattern

Multiple endpoints can answer this triple pattern.

Execution must query more than one source or build a union-style source access.

This is more expensive than `ExclusiveStatement`.

### BindingSet

A `BindingSet` is one row of variable bindings.

Example:

```text
?product = http://www.shop17.fr/product123
?label   = "Phone 123"
```

Endpoint subqueries produce streams of `BindingSet` rows. The engine joins and
filters these streams to produce the final query result.

## Query Execution Pipeline

At a high level:

```text
1. FedShop creates endpoint config.
2. FedShop starts Java FedX.
3. FedX creates a repository from endpoint config.
4. RDF4J parses SPARQL into algebra.
5. FedX optimizer extracts statement patterns.
6. Source selection maps patterns to endpoints.
7. FedX rewrites algebra nodes with source annotations.
8. Execution sends subqueries to selected endpoints.
9. Binding streams are joined locally.
10. FedX writes output files.
```

The source-selection part is the key part to understand first.

## Source Selection Algorithm

FedX's default source selection is simple.

Input:

```text
stmts: List<StatementPattern>
endpoints: List<Endpoint>
cache: SourceSelectionCache
```

Output:

```text
stmtToSources: Map<StatementPattern, List<StatementSource>>
rewritten algebra tree
```

Algorithm:

```text
for each stmt in stmts:
  if stmt already exists in stmtToSources:
    continue

  stmtToSources[stmt] = empty list
  subquery = SubQuery(stmt, dataset)

  for each endpoint in endpoints:
    assurance = cache.getAssurance(subquery, endpoint)

    if assurance == HAS_REMOTE_STATEMENTS:
      add endpoint to stmtToSources[stmt]

    else if assurance == NONE:
      skip endpoint

    else if assurance == POSSIBLY_HAS_STATEMENTS:
      schedule a remote ASK task for this endpoint + stmt

run all remote ASK tasks in parallel

for each ASK result:
  update cache
  if ASK was true:
    add endpoint to stmtToSources[stmt]

for each stmt in stmts:
  sources = stmtToSources[stmt]

  if len(sources) == 0:
    replace stmt with EmptyStatementPattern

  else if len(sources) == 1:
    replace stmt with ExclusiveStatement

  else:
    replace stmt with StatementSourcePattern
```

This is the core FedX algorithm in FedShop.

## Parallel ASK Tasks

FedX does not ask every endpoint serially.

It creates `CheckTaskPair` values:

```text
endpoint
statement pattern
query info
```

Each pair becomes a `ParallelCheckTask`.

The task does:

```text
endpoint.getTripleSource()
-> hasStatements(statement pattern, bindings, query info, dataset)
-> true or false
```

The scheduler runs these checks in parallel and a latch waits until all checks
finish or the query timeout is reached.

Data structures involved:

```text
List<CheckTaskPair> remoteCheckTasks
CountDownLatch latch
ControlledWorkerScheduler scheduler
CopyOnWriteArrayList<Exception> errors
```

The important consequence is scalability pressure:

```text
ASK count grows with triple patterns * endpoints
```

For FedShop, this matters because federation size grows up to hundreds of
endpoints.

## Endpoint Check Algorithm

The endpoint check is in `SparqlTripleSource.hasStatements`.

Input:

```text
StatementPattern stmt
BindingSet bindings
QueryInfo queryInfo
Dataset dataset
```

If ASK is enabled, FedX builds:

```sparql
ASK WHERE {
  ...
}
```

Then it:

```text
opens endpoint connection
prepares boolean query
applies timeout/inference settings
increments remote request monitoring
increments FedShop ASK counter
evaluates query
returns true or false
```

If ASK is disabled, it can fall back to:

```sparql
SELECT * WHERE {
  ...
}
LIMIT 1
```

For FedShop configs generated by `fedx.py`, ASK support is enabled:

```turtle
fedx:supportsASKQueries true .
```

## Execution After Source Selection

After source selection, execution no longer thinks in terms of raw triple
patterns only. It sees source-aware algebra nodes.

Simplified:

```text
ExclusiveStatement
-> execute against exactly one endpoint

StatementSourcePattern
-> execute against multiple candidate endpoints

EmptyStatementPattern
-> produce no bindings
```

Execution produces binding streams:

```text
endpoint subquery result
-> BindingSet
-> BindingSet
-> BindingSet
```

Then joins combine compatible bindings.

Two bindings are compatible if they agree on shared variable names.

Example:

```text
left:
  ?product = p1
  ?label = "Phone"

right:
  ?product = p1
  ?price = 100

joined:
  ?product = p1
  ?label = "Phone"
  ?price = 100
```

If shared variables disagree, the rows do not join.

## Data Shape Across One Query

For a query with 3 triple patterns and 4 endpoints:

```text
statement patterns:
  tp1
  tp2
  tp3

endpoints:
  e1
  e2
  e3
  e4
```

Source selection builds:

```text
stmtToSources:
  tp1 -> [e1, e3]
  tp2 -> [e3]
  tp3 -> []
```

Then algebra rewrite gives:

```text
tp1 -> StatementSourcePattern(e1, e3)
tp2 -> ExclusiveStatement(e3)
tp3 -> EmptyStatementPattern
```

If `tp3` is required by the query, the query may produce no result. If it is
inside an `OPTIONAL`, RDF4J's algebra semantics determine how that empty pattern
affects the final result.

## Where FedShop Instrumentation Fits

FedShop needs engine-independent output files. The original FedX engine does
not naturally write everything FedShop wants, so this fork adds instrumentation.

`FedXContainer` stores:

```text
stmtToSources
sourceSelection
triplePatternSources
askCounter
sourceSelectionTime
planningTime
```

`FedX.java` later reads this data and writes:

```text
out_result
out_source_selection
query_plan
source_selection_time.txt
planning_time.txt
ask.txt
exec_time.txt
```

Then `fedx.py` transforms these into FedShop's normalized CSV files.

## Forced Source Selection

This fork also has a forced mode:

```java
doSourceSelectionForce(stmts)
```

Forced mode uses:

```java
Map<Integer, Set<String>> triplePatternSources
```

Read it as:

```text
triple pattern number -> forced endpoint ids
```

That is not the normal FedX algorithm. It exists to inject external source
selection information for experiments.

When learning FedX, understand default mode first.

## Complexity Summary

FedX's core idea is small:

```text
for every triple pattern,
find relevant endpoints,
rewrite algebra,
execute source-aware plan
```

The difficult parts are hidden in RDF4J/FedX runtime:

- full SPARQL parsing;
- query algebra representation;
- optimizer lifecycle;
- endpoint repository abstractions;
- join execution;
- SPARQL semantics for `OPTIONAL`, `UNION`, `FILTER`, `DISTINCT`, `ORDER BY`,
  and `LIMIT`.

That is why a minimal Go implementation can copy the high-level algorithm but
still needs a careful subset of these structures.

## Minimal Go Data Model

For a FedX-like Go engine, start with these structs:

```go
type Endpoint struct {
    ID  string
    URL string
}

type Term struct {
    Kind  TermKind
    Value string
}

type TriplePattern struct {
    ID int
    S  Term
    P  Term
    O  Term
}

type StatementSource struct {
    EndpointID string
    Type       string
}

type SourceSelection map[int][]StatementSource

type Binding map[string]string
```

Then implement the algorithm in this order:

```text
parse query into triple patterns
load endpoints
ASK each endpoint for each triple pattern
build SourceSelection
execute selected subqueries
join []Binding streams
write FedShop outputs
```

This gives a FedX-like baseline. A CostFed-like engine would replace the
ASK-based source selection with summary-based source selection and add cost
estimates for planning.
