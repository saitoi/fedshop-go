# FedShop Python Pipeline Guide

This guide explains the local `fedshop-py` benchmark pipeline end to end: what each phase does, which inputs it reads, which outputs it writes, which parameters control it, and how to run a full benchmark or a single query.

All commands below assume this working directory:

```bash
cd fedshop-py
```

The default configuration is:

```text
config/config_small.yaml
```

The default benchmark output root is:

```text
benchmark/
```

The primary final output is:

```text
benchmark/metrics.csv
```

## Quick start

Run the configured smoke benchmark for `fedshop-go` and one query template:

```bash
bash run-benchmark.sh \
  --config config/config_small.yaml \
  --bench-dir benchmark \
  --engine fedshop-go \
  --query q01
```

This wrapper runs the pipeline phases in order:

1. Start Docker services for Virtuoso and the HTTP proxy.
2. Generate product, vendor, and ratingsite data.
3. Ingest the selected batches into Virtuoso.
4. Generate concrete query instances.
5. Run the selected engine.
6. Compute `benchmark/metrics.csv`.

To run exactly one evaluation attempt after data/query generation exists:

```bash
uv run fedshop evaluate run fedshop-go q01 0 0 0 \
  --config config/config_small.yaml \
  --bench-dir benchmark

uv run fedshop metrics compute benchmark/metrics.csv \
  benchmark/evaluation/fedshop-go/q01/instance_0/batch_0/attempt_0/provenance.csv \
  --config config/config_small.yaml \
  --bench-dir benchmark
```

Passing the specific `provenance.csv` is important when you want `metrics.csv` to contain only that one run. If you omit provenance files, the metrics command scans every `benchmark/evaluation/**/provenance.csv` file and includes stale runs too.

## Pipeline model

The pipeline has five logical phases.

```text
config + templates
      │
      ▼
1. generate
   data/product/
   data/dataset/*.nq
      │
      ▼
2. ingest
   Virtuoso named graphs
   data/virtuoso-proxy-mapping-batchN.json
      │
      ▼
3. query
   benchmark/generation/qXX/...
      │
      ▼
4. evaluate
   benchmark/evaluation/{engine}/qXX/instance_I/batch_B/attempt_A/...
      │
      ▼
5. metrics
   benchmark/metrics.csv
```

The implementation is a Python package named `fedshop`. The CLI entry point is:

```bash
uv run fedshop --help
```

The available command groups are:

```text
generate   Phase 1: dataset generation via WatDiv
ingest     Phase 2: load .nq files into Virtuoso and register endpoint mappings
query      Phase 3: query generation and reference execution
evaluate   Phase 4: engine evaluation
metrics    Phase 5: metrics aggregation
```

## Configuration

The default config file is `config/config_small.yaml`.

It is loaded by `fedshop.config.load_config()`, which resolves `${...}` references and a small set of local resolver expressions used by the benchmark config.

### Top-level config keys

```yaml
use_docker: true
generation: ...
evaluation: ...
```

| Key | Meaning |
|---|---|
| `use_docker` | Controls whether generated endpoint URLs use Docker host conventions where needed. |
| `generation` | Dataset, query, Virtuoso, and WatDiv settings. |
| `evaluation` | Attempts, timeout, proxy, and engine settings. |

### `generation` settings

Default values in `config/config_small.yaml`:

```yaml
generation:
  workdir: "${config_dir}/../data"
  queries_dir: "${config_dir}/../queries"
  n_batch: 2
  n_query_instances: 2
  verbose: true
  generator:
    dir: "${config_dir}/../generators/watdiv"
    exec: "${generation.generator.dir}/bin/Release/watdiv"
```

| Key | Meaning | Default in smoke config |
|---|---|---|
| `workdir` | Root for generated datasets and transient batch files. | `data/` |
| `queries_dir` | Query templates and `.const.json` files. | `queries/` |
| `n_batch` | Number of cumulative federation batches. Batch `0` has fewer members than batch `1`, etc. | `2` |
| `n_query_instances` | Number of concrete instances per query template. | `2` |
| `verbose` | Config flag retained for compatibility. | `true` |
| `generator.dir` | WatDiv source/build directory. | `generators/watdiv` |
| `generator.exec` | WatDiv executable path. | `generators/watdiv/bin/Release/watdiv` |

### Virtuoso settings

```yaml
generation:
  virtuoso:
    compose_file: "${config_dir}/../docker/virtuoso.yml"
    service_name: "bsbm-virtuoso"
    isql: "/opt/virtuoso-opensource/bin/isql"
    data_dir: "${generation.workdir}/dataset"
    port: 8890
    default_url: "http://localhost:${generation.virtuoso.port}"
    default_endpoint: "${generation.virtuoso.default_url}/sparql"
    batch_members:
      - "http://www.batch0.fr/"
      - "http://www.batch1.fr/"
    federation_members:
      batch0: ...
      batch1: ...
```

| Key | Meaning |
|---|---|
| `compose_file` | Docker Compose file used by the wrapper to start Virtuoso. |
| `service_name` | Compose service name. The code assumes the container name is `docker-{service_name}-1`. |
| `isql` | Path to the Virtuoso `isql` binary inside the container. |
| `data_dir` | Host-side dataset directory used by ingestion. |
| `port` | Virtuoso HTTP/SPARQL port. |
| `default_url` | Base Virtuoso URL. |
| `default_endpoint` | SPARQL endpoint used for reference query execution and value selection. |
| `batch_members` | Batch graph IRIs. |
| `federation_members` | Per-batch map from member names such as `vendor0` to graph IRIs such as `http://www.vendor0.fr/`. |

The smoke config uses cumulative federation size:

- `batch0`: 10 vendors + 10 ratingsites.
- `batch1`: 20 vendors + 20 ratingsites.

### Schema settings

The `generation.schema` section defines the WatDiv templates and parameters for the generated datasets.

```yaml
generation:
  schema:
    product:
      is_source: false
      provenance: http://www4.wiwiss.fu-berlin.de/bizer/bsbm/v01/vocabulary/
      template: "${config_dir}/../model/watdiv/bsbm-product.template"
      scale_factor: 1
      export_output_dir: "${generation.workdir}/product"
      params: ...

    vendor:
      is_source: true
      provenance: http://www.{%vendor_id}.fr/
      template: "${config_dir}/../model/watdiv/bsbm-vendor.template"
      export_output_dir: "${generation.workdir}/dataset"
      export_dep_output_dir: "${generation.schema.product.export_output_dir}"
      scale_factor: 1
      params: ...

    ratingsite:
      is_source: true
      provenance: http://www.{%ratingsite_id}.fr/
      template: "${config_dir}/../model/watdiv/bsbm-ratingsite.template"
      export_output_dir: "${generation.workdir}/dataset"
      export_dep_output_dir: "${generation.schema.product.export_output_dir}"
      scale_factor: 1
      params: ...
```

| Field | Meaning |
|---|---|
| `is_source` | Whether the schema section creates federation members. Products are shared input data, not federation members. |
| `provenance` | Graph/provenance IRI template injected into the WatDiv model. |
| `template` | WatDiv model template. |
| `scale_factor` | WatDiv scale factor. |
| `export_output_dir` | Directory where this section writes generated output. |
| `export_dep_output_dir` | Product dependency directory for source datasets. |
| `params` | Template placeholder values used before calling WatDiv. |

Important smoke defaults:

| Parameter | Meaning | Default |
|---|---|---|
| `product.params.product_n` | Number of products. | `20000` |
| `vendor.params.vendor_n` | Total vendors across all batches. | `10 * n_batch` |
| `ratingsite.params.ratingsite_n` | Total ratingsites across all batches. | `10 * n_batch` |

### `evaluation` settings

```yaml
evaluation:
  n_attempts: 1
  timeout: 120
  proxy:
    compose_file: "${config_dir}/../docker/proxy.yml"
    service_name: "fedshop-proxy"
    host: "localhost"
    port: 5555
    endpoint: "http://${evaluation.proxy.host}:${evaluation.proxy.port}/"
    container_name: "docker-fedshop-proxy-1"
  engines:
    fedshop-go: ...
    fedx: ...
    rsa: ...
```

| Key | Meaning | Default |
|---|---|---|
| `n_attempts` | Number of repeated attempts per `(engine, query, instance, batch)`. | `1` |
| `timeout` | Per-engine run timeout in seconds. | `120` |
| `proxy` | HTTP proxy used to count requests, ASK requests, and transfer. | `localhost:5555` |
| `engines` | Engine-specific settings. `evaluate run-all` iterates over these engine names unless filtered. | `fedshop-go`, `fedx`, `rsa` in config |

### `fedshop-go` engine settings

```yaml
evaluation:
  engines:
    fedshop-go:
      dir: "${config_dir}/../../go-engine"
      selector: ask
      cache: memory
      join: bind
      planner: source-count
      exclusive_groups: true
      failure_policy: strict
      max_concurrency: 4
      bind_batch_size: 20
      retry_count: 2
```

| Key | Meaning | Values/defaults |
|---|---|---|
| `dir` | Path to the Go engine repository. | `../../go-engine` |
| `selector` | Source-selection strategy passed to `fedshop-go query`. | `ask`, `broadcast`, `summary`; default here `ask` |
| `cache` | Go engine cache mode. | `off`, `memory`; default here `memory` |
| `join` | Go engine join algorithm. | `bind`, `hash`; default here `bind` |
| `planner` | Go engine planner. | `source-count`, `cost`; default here `source-count` |
| `exclusive_groups` | Adds `--exclusive-groups` when true. | default `true` |
| `failure_policy` | How the engine handles endpoint failures. | `strict`, `partial`; default `strict` |
| `max_concurrency` | Max concurrent engine HTTP work. | default `4` |
| `bind_batch_size` | Bound-join batch size. | default `20` |
| `retry_count` | Endpoint retry count. | default `2` |
| `http_proxy` | Optional. If set, Go engine traffic is routed through this HTTP proxy and proxy stats are collected. | unset by default |

If `selector: summary`, build a summary first:

```bash
uv run fedshop evaluate prerequisites fedshop-go --config config/config_small.yaml
uv run fedshop evaluate generate-config fedshop-go 0 --config config/config_small.yaml
uv run fedshop evaluate build-summary 0 --config config/config_small.yaml
```

The summary output is:

```text
../go-engine/target/summary/summary_batch0.json
```

## Wrapper script: `run-benchmark.sh`

Use the wrapper for normal local runs:

```bash
bash run-benchmark.sh [options]
```

Options:

| Option | Meaning | Default |
|---|---|---|
| `--config PATH` | Config file. | `config/config_small.yaml` |
| `--bench-dir PATH` | Benchmark output root. | `benchmark` |
| `--engine NAME` | Restrict evaluation to one engine. | all configured engines |
| `--query NAME` | Restrict query generation/evaluation to one query template, e.g. `q01`. | all generated templates |
| `--skip-docker` | Do not start Virtuoso/proxy containers. Use when services are already running. | false |
| `--skip-generate` | Skip data generation. | false |
| `--skip-ingest` | Skip Virtuoso ingestion. | false |
| `--skip-queries` | Skip query generation/reference execution. | false |
| `--skip-evaluate` | Skip engine execution. Metrics still run. | false |
| `-h`, `--help` | Show wrapper help. | n/a |

The wrapper always computes metrics at the end:

```bash
uv run fedshop metrics compute "$BENCH_DIR/metrics.csv" \
  --config "$CONFIG" \
  --bench-dir "$BENCH_DIR"
```

Because no explicit provenance files are passed, this includes all provenance files currently under:

```text
$BENCH_DIR/evaluation/**/provenance.csv
```

If you need a clean one-query `metrics.csv`, either use a fresh `--bench-dir` or run `metrics compute` manually with explicit provenance file paths.

## Phase 0: services

The wrapper starts two Docker Compose stacks:

```bash
docker compose -f docker/virtuoso.yml up -d
docker compose -f docker/proxy.yml up -d
```

It then waits for:

```text
http://localhost:8890/sparql?query=ASK+%7B+%3Fs+%3Fp+%3Fo+%7D
http://localhost:5555/get-stats
```

Service roles:

| Service | Purpose |
|---|---|
| Virtuoso | Stores generated `.nq` datasets in named graphs and serves SPARQL. |
| FedShop proxy | Counts HTTP requests, ASK requests, and data transfer for engines that use it. |

Proxy API used by adapters:

| Endpoint | Purpose |
|---|---|
| `GET /reset` | Reset counters before an evaluation attempt. |
| `GET /get-stats` | Return `NB_HTTP_REQ`, `NB_ASK`, and `DATA_TRANSFER`. |

## Phase 1: data generation

Commands:

```bash
uv run fedshop generate products --config config/config_small.yaml
uv run fedshop generate sources --config config/config_small.yaml
```

The wrapper currently calls `generate products` twice and then `generate sources`. `generate sources` also calls `generate_products()` internally before generating vendors and ratingsites. This is redundant but harmless: product data is regenerated before source generation.

### `generate products`

CLI:

```bash
uv run fedshop generate products \
  --config config/config_small.yaml \
  [--output-dir PATH]
```

Options:

| Option | Meaning | Default |
|---|---|---|
| `--config PATH` | Config file. | `fedshop-py/config/config_small.yaml` |
| `--output-dir PATH` | Override product output directory. | `generation.schema.product.export_output_dir` |

Inputs:

| Input | Path from smoke config |
|---|---|
| Product WatDiv template | `model/watdiv/bsbm-product.template` |
| Product schema params | `generation.schema.product.params` |
| WatDiv executable wrapper | `fedshop.watdiv.run()` |

Outputs:

| Output | Path |
|---|---|
| Temporary rendered WatDiv model | `data/product/product.txt.tmp` |
| Generated product data | `data/product/` |

### `generate sources`

CLI:

```bash
uv run fedshop generate sources \
  --config config/config_small.yaml \
  [--section vendor|ratingsite --id N]
```

Options:

| Option | Meaning |
|---|---|
| `--config PATH` | Config file. |
| `--section vendor|ratingsite` | Generate only one source section. Must be used with `--id`. |
| `--id N` | Generate only one source id for the selected section. |

Default behavior without `--section`/`--id`:

- Generate products.
- Generate all vendors from `0` to `(n_batch * 10) - 1`.
- Generate all ratingsites from `0` to `(n_batch * 10) - 1`.

With the smoke config (`n_batch: 2`), that means:

```text
vendor0.nq ... vendor19.nq
ratingsite0.nq ... ratingsite19.nq
```

Inputs:

| Input | Path/config |
|---|---|
| Vendor template | `model/watdiv/bsbm-vendor.template` |
| Ratingsite template | `model/watdiv/bsbm-ratingsite.template` |
| Product dependency data | `data/product/` |
| Vendor/ratingsite params | `generation.schema.vendor.params`, `generation.schema.ratingsite.params` |

Outputs:

| Output | Path |
|---|---|
| Temporary vendor model files | `data/dataset/vendorN.txt.tmp` |
| Temporary ratingsite model files | `data/dataset/ratingsiteN.txt.tmp` |
| Vendor RDF data | `data/dataset/vendorN.nq` |
| Ratingsite RDF data | `data/dataset/ratingsiteN.nq` |

## Phase 2: ingestion

Command:

```bash
uv run fedshop ingest batch 0 --config config/config_small.yaml
```

CLI:

```bash
uv run fedshop ingest batch BATCH_ID \
  --config config/config_small.yaml
```

Arguments/options:

| Argument/option | Meaning |
|---|---|
| `BATCH_ID` | Numeric batch id, starting at `0`. |
| `--config PATH` | Config file. |

What it does:

1. Grants required Virtuoso SPARQL permissions.
2. Reads the configured federation members for `batch{BATCH_ID}`.
3. For each member, loads `data/dataset/{member_name}.nq` into the member graph IRI.
4. Clears the graph before loading, so reruns replace graph content.
5. Writes a proxy/endpoint mapping JSON file.

Inputs:

| Input | Path/config |
|---|---|
| Dataset files | `data/dataset/vendorN.nq`, `data/dataset/ratingsiteN.nq` |
| Federation member map | `generation.virtuoso.federation_members.batchN` |
| Virtuoso container | `docker-{generation.virtuoso.service_name}-1` |
| Virtuoso `isql` path | `generation.virtuoso.isql` |

Outputs:

| Output | Path |
|---|---|
| Loaded named graphs | Virtuoso |
| Batch endpoint mapping | `data/virtuoso-proxy-mapping-batchN.json` |

Mapping file format:

```json
{
  "http://www.vendor0.fr/": "http://host.docker.internal:8890/sparql?default-graph-uri=http%3A%2F%2Fwww.vendor0.fr%2F",
  "http://www.ratingsite0.fr/": "http://host.docker.internal:8890/sparql?default-graph-uri=http%3A%2F%2Fwww.ratingsite0.fr%2F"
}
```

When `use_docker: true`, registered endpoint URLs use `host.docker.internal` for container-to-host access. The `fedshop-go` adapter rewrites these to `localhost` unless `http_proxy` is configured, because the Go engine runs on the host.

## Phase 3: query generation

Command:

```bash
uv run fedshop query run-all \
  --config config/config_small.yaml \
  --bench-dir benchmark \
  --batch-id 0 \
  --query-name q01
```

CLI:

```bash
uv run fedshop query run-all \
  --config PATH \
  --bench-dir PATH \
  --batch-id BATCH_ID \
  [--query-name qXX]
```

Options:

| Option | Meaning | Default |
|---|---|---|
| `--config PATH` | Config file. | `fedshop-py/config/config_small.yaml` |
| `--bench-dir PATH` | Output root. | `fedshop-py/benchmark` |
| `--batch-id N` | Batch used for reference execution and endpoint fallback mapping. | `0` |
| `--query-name qXX` | Restrict to one template. | all `queries/q*.sparql` templates |

Inputs:

| Input | Path |
|---|---|
| Query templates | `queries/q01.sparql` ... `queries/q12.sparql` |
| Constant metadata | `queries/q01.const.json` ... `queries/q12.const.json` |
| Virtuoso endpoint | `generation.virtuoso.default_endpoint` |
| Batch mapping, if present | `data/virtuoso-proxy-mapping-batchN.json` |

Templates without a matching `.const.json` are skipped.

### Query-generation steps

For each selected query template:

1. Parse the SPARQL template.
2. Use the `.const.json` file to build value-selection subqueries.
3. Execute value-selection subqueries against Virtuoso.
4. Join and sample enough rows for `generation.n_query_instances`.
5. Instantiate concrete SPARQL queries by injecting selected constant values.
6. Decompose the injected query into triple-pattern ids (`tp0`, `tp1`, ...).
7. Execute each injected query as a reference query for the current batch.

Reference execution uses the default Virtuoso endpoint with one `default-graph-uri` parameter per graph in the batch mapping. For source-local reference queries (`q06`, `q08`, `q09`, `q10`, `q11`, `q12`), it can execute against scoped endpoints to preserve source-local semantics.

### Query-generation outputs

For query `q01`, output root:

```text
benchmark/generation/q01/
```

Files:

| Output | Path | Meaning |
|---|---|---|
| Value-selection subqueries | `benchmark/generation/q01/value_selection.json` | Generated SPARQL subqueries used to find concrete placeholder values. |
| Sampled workload values | `benchmark/generation/q01/workload_value_selection.csv` | Rows of concrete values for placeholders. |
| Injected SPARQL query | `benchmark/generation/q01/instance_0/injected.sparql` | Concrete benchmark query for one instance. |
| Triple-pattern composition | `benchmark/generation/q01/instance_0/composition.json` | Mapping from `tpN` to `[subject, predicate, object]`. |
| Reference results | `benchmark/generation/q01/instance_0/results-batch0.csv` | Reference result set from Virtuoso for this batch. |

Example layout:

```text
benchmark/generation/
└── q01/
    ├── value_selection.json
    ├── workload_value_selection.csv
    ├── instance_0/
    │   ├── injected.sparql
    │   ├── composition.json
    │   └── results-batch0.csv
    └── instance_1/
        ├── injected.sparql
        ├── composition.json
        └── results-batch0.csv
```

Important reuse behavior:

- For `batch_id == 0`, `value_selection.json`, `injected.sparql`, and `composition.json` are generated or regenerated.
- For `batch_id > 0`, existing value selection and injected queries are reused when valid.
- `results-batchN.csv` is generated per batch because result cardinality can change as federation size changes.

## Phase 4: evaluation

Evaluation runs engines against generated concrete queries.

Single run:

```bash
uv run fedshop evaluate run fedshop-go q01 0 0 0 \
  --config config/config_small.yaml \
  --bench-dir benchmark
```

All configured combinations:

```bash
uv run fedshop evaluate run-all \
  --config config/config_small.yaml \
  --bench-dir benchmark
```

Filtered run-all:

```bash
uv run fedshop evaluate run-all \
  --config config/config_small.yaml \
  --bench-dir benchmark \
  --engine fedshop-go \
  --query q01
```

### `evaluate prerequisites`

CLI:

```bash
uv run fedshop evaluate prerequisites ENGINE \
  --config config/config_small.yaml
```

Supported adapter names in the implementation:

```text
fedshop-go
fedx
pyfedx
costfed
```

Behavior:

| Engine | Prerequisite action |
|---|---|
| `fedshop-go` | Runs `go build -o fedshop-go ./cmd/fedshop-go` in `../go-engine` with `GOCACHE=../go-engine/.gocache`. |
| `fedx` | Runs Maven build in the configured FedX directory. |
| `pyfedx` | Verifies `pyfedx.py` exists. |
| `costfed` | Runs Maven build for CostFed modules. |

If the engine name is unknown, the CLI prints a warning and skips prerequisites.

The smoke config also contains an `rsa` entry, but this `fedshop-py` implementation does not currently include an `rsa` adapter in the evaluation adapter map. If you run without `--engine`, `rsa` is selected from the config and then skipped with a warning during evaluation. Use `--engine fedshop-go`, `--engine fedx`, `--engine pyfedx`, or `--engine costfed` for implemented adapters.

### `evaluate generate-config`

CLI:

```bash
uv run fedshop evaluate generate-config ENGINE BATCH_ID \
  --config config/config_small.yaml
```

What it does:

1. Reads `data/virtuoso-proxy-mapping-batchN.json`.
2. Calls the selected engine adapter.
3. Writes the engine-specific federation config.

Common outputs:

| Engine | Output |
|---|---|
| `fedshop-go` | `../go-engine/target/config/config_batchN.ttl` |
| `fedx` | configured FedX dir: `target/config/config_batchN.ttl` |
| `pyfedx` | configured pyfedx dir: `target/config/config_batchN.ttl` |
| `costfed` | configured CostFed dir: `summaries/endpoints_batchN.txt`, `summaries/sum_fedshop_batchN.n3`, patched `costfed/costfed.props` |

The Turtle config format used by `fedshop-go`, `fedx`, and `pyfedx` looks like:

```turtle
@prefix sd: <http://www.w3.org/ns/sparql-service-description#> .
@prefix fedx: <http://rdf4j.org/config/federation#> .

<http://www.vendor0.fr/> a sd:Service ;
    fedx:store "SPARQLEndpoint";
    sd:endpoint "http://localhost:8890/sparql?default-graph-uri=http%3A%2F%2Fwww.vendor0.fr%2F";
    fedx:supportsASKQueries true .
```

### `evaluate build-summary`

CLI:

```bash
uv run fedshop evaluate build-summary BATCH_ID \
  --config config/config_small.yaml
```

This command is specific to `fedshop-go`.

Input:

```text
../go-engine/target/config/config_batchN.ttl
```

Output:

```text
../go-engine/target/summary/summary_batchN.json
```

Use it when `evaluation.engines.fedshop-go.selector` is `summary` or when testing Go engine summary-based planning.

### `evaluate run`

CLI:

```bash
uv run fedshop evaluate run ENGINE QUERY_NAME INSTANCE_ID BATCH_ID ATTEMPT \
  --config config/config_small.yaml \
  --bench-dir benchmark \
  [--noexec]
```

Arguments:

| Argument | Meaning | Example |
|---|---|---|
| `ENGINE` | Engine adapter name. | `fedshop-go` |
| `QUERY_NAME` | Query template name. | `q01` |
| `INSTANCE_ID` | Concrete query instance id. | `0` |
| `BATCH_ID` | Federation batch id. | `0` |
| `ATTEMPT` | Attempt id. | `0` |

Options:

| Option | Meaning |
|---|---|
| `--config PATH` | Config file. |
| `--bench-dir PATH` | Benchmark root containing `generation/` and receiving `evaluation/`. |
| `--noexec` | Do not execute the engine. The run is recorded as `timeout`. Useful for testing output plumbing. |

Inputs:

| Input | Path |
|---|---|
| Injected query | `benchmark/generation/qXX/instance_I/injected.sparql` |
| Composition file | `benchmark/generation/qXX/instance_I/composition.json` |
| Batch mapping | `data/virtuoso-proxy-mapping-batchB.json` |
| Engine-specific generated config | Adapter-specific path, often created automatically during the run. |

Output directory:

```text
benchmark/evaluation/{engine}/{query}/instance_{instance}/batch_{batch}/attempt_{attempt}/
```

For example:

```text
benchmark/evaluation/fedshop-go/q01/instance_0/batch_0/attempt_0/
```

Standard outputs:

| File | Meaning |
|---|---|
| `results.txt` | Raw engine result file. Format is engine-specific. |
| `source_selection.txt` | Raw engine source-selection file. Format is engine-specific. |
| `query_plan.txt` | Raw engine query plan file. Format is engine-specific. |
| `results.csv` | Normalized result CSV generated by the adapter. |
| `provenance.csv` | Normalized source-selection/provenance CSV generated by the adapter. This is the main input to metrics. |
| `stats.csv` | Normalized per-attempt timing/request stats. |

Engine-specific extra outputs may also appear:

| Engine | Extra file examples |
|---|---|
| `fedshop-go` | `fedshop_go_stats.json` |
| `pyfedx` | `pyfedx_stats.json` |
| `fedx`/`costfed` | `exec_time.txt`, `http_req.txt`, `ask.txt`, `data_transfer.txt` |

### `evaluate run-all`

CLI:

```bash
uv run fedshop evaluate run-all \
  --config config/config_small.yaml \
  --bench-dir benchmark \
  [--engine ENGINE] \
  [--query qXX]
```

Options:

| Option | Meaning | Default |
|---|---|---|
| `--config PATH` | Config file. | `fedshop-py/config/config_small.yaml` |
| `--bench-dir PATH` | Benchmark root. | `fedshop-py/benchmark` |
| `--engine ENGINE` | Restrict to one engine. | all engines in config |
| `--query qXX` | Restrict to one generated query directory. | all directories under `benchmark/generation/` |

Iteration order:

```text
for engine in selected engines:
  for query in selected generated queries:
    for instance in range(generation.n_query_instances):
      for batch in range(generation.n_batch):
        for attempt in range(evaluation.n_attempts):
          evaluate run
```

With the smoke config and `--engine fedshop-go --query q01`, this means:

```text
1 engine × 1 query × 2 instances × 2 batches × 1 attempt = 4 runs
```

### Timeout propagation

If `batch > 0`, evaluation checks the previous batch's `results.txt` and adjacent `stats.csv`.

If the previous batch timed out, the current batch is marked as timeout without executing the engine. This prevents later cumulative batches from running after an earlier timeout for the same engine/query/instance/attempt.

The generated `stats.csv` row uses:

```text
exec_time=timeout
source_selection_time=timeout
planning_time=timeout
ask=timeout
http_req=timeout
data_transfer=timeout
```

### Missing generated query

If `benchmark/generation/qXX/instance_I/injected.sparql` does not exist, the run is skipped and `stats.csv` is written with:

```text
exec_time=no_query
```

The usual artifact files are truncated or touched so stale output from older runs is not reused.

## Engine adapter normalization

Each engine can emit different raw formats. The adapter layer normalizes them.

### Normalized `stats.csv`

Columns:

```text
engine,query,instance,batch,attempt,exec_time,source_selection_time,planning_time,ask,http_req,data_transfer
```

Column meanings:

| Column | Meaning |
|---|---|
| `engine` | Engine name from the evaluation path. |
| `query` | Query name, e.g. `q01`. |
| `instance` | Query instance id. |
| `batch` | Batch id. |
| `attempt` | Attempt id. |
| `exec_time` | Runtime seconds, or status such as `timeout`, `no_query`, `error_runtime`. |
| `source_selection_time` | Engine-reported source-selection seconds, or failure status. |
| `planning_time` | Engine-reported planning seconds, or failure status. |
| `ask` | ASK request count, or failure status. |
| `http_req` | HTTP request count, or failure status. |
| `data_transfer` | Proxy/engine data-transfer metric, or failure status. |

### Normalized `results.csv`

This is a standard CSV table of query result bindings. The columns depend on the SPARQL query projection.

If the engine returns no results, or the run fails before normalized results are available, this file can be empty.

### Normalized `provenance.csv`

This file maps each result row to selected sources per triple pattern.

Columns are triple-pattern ids:

```text
tp0,tp1,tp2,...
```

Each cell contains a selected source id/IRI for that triple pattern. Multiple selected sources for one triple pattern are represented by multiple rows after adapter normalization/padding.

`metrics compute` reads this file to calculate source-selection metrics.

## Phase 5: metrics

Command:

```bash
uv run fedshop metrics compute benchmark/metrics.csv \
  --config config/config_small.yaml \
  --bench-dir benchmark
```

CLI:

```bash
uv run fedshop metrics compute OUTFILE [PROVENANCE_FILES...] \
  --config PATH \
  --bench-dir PATH
```

Arguments/options:

| Argument/option | Meaning |
|---|---|
| `OUTFILE` | Destination CSV path, e.g. `benchmark/metrics.csv`. |
| `PROVENANCE_FILES...` | Optional explicit provenance files. If omitted, the command auto-discovers all provenance files under `--bench-dir`. |
| `--config PATH` | Config file. Used to compute total source counts per batch. |
| `--bench-dir PATH` | Benchmark root used for auto-discovery. |

Auto-discovery pattern:

```text
{bench_dir}/evaluation/**/provenance.csv
```

Explicit one-run metrics example:

```bash
uv run fedshop metrics compute benchmark/metrics.csv \
  benchmark/evaluation/fedshop-go/q01/instance_0/batch_0/attempt_0/provenance.csv \
  --config config/config_small.yaml \
  --bench-dir benchmark
```

Multiple explicit runs:

```bash
uv run fedshop metrics compute benchmark/metrics.csv \
  benchmark/evaluation/fedshop-go/q01/instance_0/batch_0/attempt_0/provenance.csv \
  benchmark/evaluation/fedshop-go/q01/instance_1/batch_0/attempt_0/provenance.csv \
  --config config/config_small.yaml \
  --bench-dir benchmark
```

### Metrics input path contract

The metrics parser expects provenance files to live under this path shape:

```text
.../{engine}/{query}/instance_{instance}/batch_{batch}/attempt_{attempt}/provenance.csv
```

Example:

```text
benchmark/evaluation/fedshop-go/q01/instance_0/batch_0/attempt_0/provenance.csv
```

Files outside that shape are ignored.

### Metrics output columns

For evaluation-mode paths, output rows include:

```text
attempt,engine,status,query,instance,batch,nb_results,nb_distinct_sources,
relevant_sources_selectivity,tpwss,avg_rwss,min_rwss,max_rwss
```

Column meanings:

| Column | Meaning |
|---|---|
| `attempt` | Attempt id parsed from the path. |
| `engine` | Engine parsed from the path. |
| `status` | Derived from adjacent `stats.csv`. `ok` when `exec_time` is numeric. Otherwise `timeout`, `no_query`, `error_runtime`, etc. |
| `query` | Query name parsed from the path. |
| `instance` | Instance id parsed from the path. |
| `batch` | Batch id parsed from the path. |
| `nb_results` | Number of rows in adjacent `results.csv`, if non-empty. |
| `nb_distinct_sources` | Number of distinct source ids in `provenance.csv`. |
| `relevant_sources_selectivity` | `nb_distinct_sources / total_sources_for_batch`. |
| `tpwss` | Total per-triple-pattern-wise source selection: sum of distinct sources per triple-pattern column. |
| `avg_rwss` | Row-wise source-selection average. Currently omitted for evaluation-mode rows. |
| `min_rwss` | Row-wise source-selection minimum. Currently omitted for evaluation-mode rows. |
| `max_rwss` | Row-wise source-selection maximum. Currently omitted for evaluation-mode rows. |

For failed attempts where `status` is not `ok` or `missing_stats`, metric fields are written as empty/NaN.

### Total source count by batch

Metrics computes the total number of sources per batch from the configured vendor and ratingsite counts.

With the smoke config:

| Batch | Vendors | Ratingsites | Total sources |
|---|---:|---:|---:|
| `0` | 10 | 10 | 20 |
| `1` | 20 | 20 | 40 |

That total is used by:

```text
relevant_sources_selectivity = nb_distinct_sources / total_sources_for_batch
```

## Common workflows

### Full smoke run for `fedshop-go`

```bash
cd fedshop-py

bash run-benchmark.sh \
  --config config/config_small.yaml \
  --bench-dir benchmark \
  --engine fedshop-go
```

This runs all generated query templates in the smoke config for `fedshop-go`.

### One query template through the wrapper

```bash
cd fedshop-py

bash run-benchmark.sh \
  --config config/config_small.yaml \
  --bench-dir benchmark-q01 \
  --engine fedshop-go \
  --query q01
```

Using a fresh `--bench-dir` avoids mixing old provenance files into metrics.

Final output:

```text
benchmark-q01/metrics.csv
```

### Exactly one query instance, one batch, one attempt

Start services if they are not already running:

```bash
docker compose -f docker/virtuoso.yml up -d
docker compose -f docker/proxy.yml up -d
```

Generate and ingest only what is needed:

```bash
uv run fedshop generate products --config config/config_small.yaml
uv run fedshop generate sources --config config/config_small.yaml
uv run fedshop ingest batch 0 --config config/config_small.yaml
```

Generate only `q01` for batch `0`:

```bash
uv run fedshop query run-all \
  --config config/config_small.yaml \
  --bench-dir benchmark-one \
  --batch-id 0 \
  --query-name q01
```

Build and run `fedshop-go` once:

```bash
uv run fedshop evaluate prerequisites fedshop-go \
  --config config/config_small.yaml

uv run fedshop evaluate run fedshop-go q01 0 0 0 \
  --config config/config_small.yaml \
  --bench-dir benchmark-one
```

Compute metrics from only that attempt:

```bash
uv run fedshop metrics compute benchmark-one/metrics.csv \
  benchmark-one/evaluation/fedshop-go/q01/instance_0/batch_0/attempt_0/provenance.csv \
  --config config/config_small.yaml \
  --bench-dir benchmark-one
```

Final output:

```text
benchmark-one/metrics.csv
```

### Recompute metrics only

For all existing evaluation artifacts:

```bash
uv run fedshop metrics compute benchmark/metrics.csv \
  --config config/config_small.yaml \
  --bench-dir benchmark
```

For only one query:

```bash
uv run fedshop metrics compute benchmark/metrics-q01.csv \
  benchmark/evaluation/fedshop-go/q01/instance_0/batch_0/attempt_0/provenance.csv \
  benchmark/evaluation/fedshop-go/q01/instance_1/batch_0/attempt_0/provenance.csv \
  --config config/config_small.yaml \
  --bench-dir benchmark
```

For shell expansion of all `q01` attempts:

```bash
uv run fedshop metrics compute benchmark/metrics-q01.csv \
  benchmark/evaluation/fedshop-go/q01/instance_*/batch_*/attempt_*/provenance.csv \
  --config config/config_small.yaml \
  --bench-dir benchmark
```

## Output directory reference

Typical smoke run layout:

```text
fedshop-py/
├── data/
│   ├── product/
│   │   └── product.txt.tmp
│   ├── dataset/
│   │   ├── vendor0.nq
│   │   ├── ratingsite0.nq
│   │   └── ...
│   └── virtuoso-proxy-mapping-batch0.json
├── benchmark/
│   ├── generation/
│   │   └── q01/
│   │       ├── value_selection.json
│   │       ├── workload_value_selection.csv
│   │       └── instance_0/
│   │           ├── injected.sparql
│   │           ├── composition.json
│   │           └── results-batch0.csv
│   ├── evaluation/
│   │   └── fedshop-go/
│   │       └── q01/
│   │           └── instance_0/
│   │               └── batch_0/
│   │                   └── attempt_0/
│   │                       ├── results.txt
│   │                       ├── source_selection.txt
│   │                       ├── query_plan.txt
│   │                       ├── results.csv
│   │                       ├── provenance.csv
│   │                       ├── stats.csv
│   │                       └── fedshop_go_stats.json
│   └── metrics.csv
└── ../go-engine/
    ├── fedshop-go
    └── target/
        ├── config/
        │   └── config_batch0.ttl
        └── summary/
            └── summary_batch0.json
```

## Query inputs

The repository includes 12 query templates:

```text
queries/q01.sparql
queries/q02.sparql
...
queries/q12.sparql
```

Each template should have a matching constant metadata file:

```text
queries/q01.const.json
queries/q02.const.json
...
queries/q12.const.json
```

The `.const.json` file tells query generation which variables must be selected and injected. The query generator supports metadata such as:

| Field pattern | Meaning |
|---|---|
| `exclusive` | Build a value-selection subquery for only that variable. |
| `ignoreFilter` | Exclude that variable from filter handling during value selection. |
| `query` | Expression used to derive or constrain constants, e.g. word-in-label or date comparisons. |

The generator parses SPARQL using RDFLib, manipulates algebra, and serializes back to SPARQL.

## Engine-specific notes

### `fedshop-go`

The adapter builds:

```bash
go build -o fedshop-go ./cmd/fedshop-go
```

It then runs:

```bash
../go-engine/fedshop-go query \
  --config ../go-engine/target/config/config_batchN.ttl \
  --query benchmark/generation/qXX/instance_I/injected.sparql \
  --out-result .../results.txt \
  --out-source-selection .../source_selection.txt \
  --query-plan .../query_plan.txt \
  --stats .../fedshop_go_stats.json \
  --timeout 120s \
  --selector ask \
  --cache memory \
  --join bind \
  --planner source-count \
  --failure-policy strict \
  --max-concurrency 4 \
  --bind-batch-size 20 \
  --retry-count 2 \
  --exclusive-groups
```

Those options come from `evaluation.engines.fedshop-go`.

The adapter writes normalized `stats.csv` by combining:

- the Go engine JSON stats file;
- wall-clock elapsed time;
- optional proxy stats if `http_proxy` is configured.

### `fedx`

The adapter:

- builds with Maven;
- writes `target/config/config_batchN.ttl`;
- runs Java through `mvn exec:java`;
- routes Java HTTP through the configured proxy;
- normalizes FedX text output into `results.csv` and `provenance.csv`.

The Java command includes:

```text
-Dhttp.nonProxyHosts="host.docker.internal|localhost|127.0.0.1"
-Dhttp.keepAlive=false
```

These avoid proxying local traffic and reduce stale connection failures.

### `pyfedx`

The adapter:

- verifies `pyfedx.py` exists;
- writes the same Turtle config shape as FedX;
- runs the Python script;
- copies CSV results directly;
- normalizes source selection into `provenance.csv`.

### `costfed`

The adapter:

- builds the required Maven modules;
- writes `summaries/endpoints_batchN.txt`;
- generates or refreshes `summaries/sum_fedshop_batchN.n3`;
- patches `costfed/costfed.props` to point at the current summary;
- normalizes output into standard benchmark artifacts.

## Parameter cheat sheet

### Run fewer things

| Goal | Command/setting |
|---|---|
| One query template through wrapper | `bash run-benchmark.sh --engine fedshop-go --query q01` |
| One query template in query generation | `uv run fedshop query run-all --query-name q01 ...` |
| One query template in evaluation run-all | `uv run fedshop evaluate run-all --query q01 ...` |
| One engine in evaluation run-all | `uv run fedshop evaluate run-all --engine fedshop-go ...` |
| One exact attempt | `uv run fedshop evaluate run fedshop-go q01 0 0 0 ...` |
| One batch during query generation | `uv run fedshop query run-all --batch-id 0 ...` |
| Fewer batches globally | Edit `generation.n_batch`. |
| Fewer query instances globally | Edit `generation.n_query_instances`. |
| Fewer attempts globally | Edit `evaluation.n_attempts`. |

### Preserve existing work

| Goal | Wrapper flags |
|---|---|
| Services already running | `--skip-docker` |
| Data already generated | `--skip-generate` |
| Data already ingested | `--skip-ingest` |
| Queries already generated | `--skip-queries` |
| Evaluation already done; recompute metrics only | `--skip-docker --skip-generate --skip-ingest --skip-queries --skip-evaluate` |

Example metrics-only wrapper run:

```bash
bash run-benchmark.sh \
  --config config/config_small.yaml \
  --bench-dir benchmark \
  --skip-docker \
  --skip-generate \
  --skip-ingest \
  --skip-queries \
  --skip-evaluate
```

For precise metrics-only work, prefer the direct `metrics compute` command with explicit provenance files.

## Troubleshooting

### `metrics.csv` includes old runs

Cause: `metrics compute` auto-discovers all provenance files under `benchmark/evaluation/**/provenance.csv`.

Fix: use a fresh `--bench-dir`, delete stale evaluation output, or pass explicit provenance files:

```bash
uv run fedshop metrics compute benchmark/metrics.csv \
  benchmark/evaluation/fedshop-go/q01/instance_0/batch_0/attempt_0/provenance.csv \
  --config config/config_small.yaml \
  --bench-dir benchmark
```

### `No provenance files found`

Cause: no evaluation run produced `provenance.csv` under the selected `--bench-dir`, and no explicit provenance files were passed.

Check:

```bash
find benchmark/evaluation -name provenance.csv
```

Then either run evaluation or pass the correct files explicitly.

### Evaluation says `no_query`

Cause: the injected query does not exist:

```text
benchmark/generation/qXX/instance_I/injected.sparql
```

Fix: run query generation first:

```bash
uv run fedshop query run-all \
  --config config/config_small.yaml \
  --bench-dir benchmark \
  --batch-id 0 \
  --query-name qXX
```

### Later batches immediately time out

Cause: timeout propagation. If batch `B-1` timed out for the same engine/query/instance/attempt, batch `B` is marked timeout without execution.

Check:

```bash
cat benchmark/evaluation/fedshop-go/q01/instance_0/batch_0/attempt_0/stats.csv
```

### `fedshop-go` config points to `host.docker.internal`

The Go adapter rewrites `host.docker.internal` to `localhost` unless `http_proxy` is configured. Regenerate config through the adapter:

```bash
uv run fedshop evaluate generate-config fedshop-go 0 \
  --config config/config_small.yaml
```

### Proxy counters are zero for `fedshop-go`

By default, `fedshop-go` does not use the HTTP proxy unless `evaluation.engines.fedshop-go.http_proxy` is set. Without `http_proxy`, request counts come from Go engine stats where available, not from the FedShop proxy.

### Docker services are already running

Use:

```bash
bash run-benchmark.sh --skip-docker ...
```

### `uv run` uses the wrong environment

The package requires Python `>=3.12` according to `pyproject.toml`. Use the local `uv` environment from `fedshop-py/`.

Check:

```bash
uv run python --version
uv run fedshop --help
```

## Verification commands

Use these to inspect a run:

```bash
find benchmark/generation/q01 -maxdepth 3 -type f | sort
find benchmark/evaluation/fedshop-go/q01 -maxdepth 5 -type f | sort
sed -n '1,20p' benchmark/evaluation/fedshop-go/q01/instance_0/batch_0/attempt_0/stats.csv
sed -n '1,20p' benchmark/evaluation/fedshop-go/q01/instance_0/batch_0/attempt_0/provenance.csv
sed -n '1,20p' benchmark/metrics.csv
```

Use these to confirm services:

```bash
curl -sf "http://localhost:8890/sparql?query=ASK+%7B+%3Fs+%3Fp+%3Fo+%7D"
curl -sf "http://localhost:5555/get-stats"
```

Use these to confirm the CLI:

```bash
uv run fedshop --help
uv run fedshop generate --help
uv run fedshop ingest --help
uv run fedshop query --help
uv run fedshop evaluate --help
uv run fedshop metrics --help
```
