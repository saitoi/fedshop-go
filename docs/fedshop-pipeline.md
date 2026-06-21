# FedShop Benchmark Pipeline

This document describes the four phases of the FedShop benchmark: dataset generation, ingestion, query generation, and evaluation. The goal is to provide enough concrete detail to reimplement the pipeline in plain Python with uv, without Snakemake or OmegaConf.

---

## Overview

FedShop measures how well a federated SPARQL engine performs source selection across a growing set of endpoints. The federation is structured as a set of vendors and rating sites that each host a slice of a product catalogue. The benchmark varies federation size in discrete steps called batches, with each batch adding more endpoints and therefore more data to distribute across the federation.

The four phases form a strict dependency chain. You first generate the raw RDF data, then load it into Virtuoso and configure one SPARQL endpoint per federation member, then instantiate concrete query workloads against that data, and finally run each engine under evaluation and collect metrics. Phases one through three are one-time setup; phase four is repeated for every engine.

---

## 1. Dataset Generation

The data generator is WatDiv, a C++ binary that takes a template file and a scale factor and writes N-Quads to stdout. FedShop has its own BSBM-flavoured templates for three entity types: products, vendors, and rating sites.

Products are generated once and are federation-agnostic. They represent the shared catalogue that every vendor and rating site references. The product template is parameterised with counts for the number of products, producers, features, and types, all of which are computed from a single `product_n` value (typically 20 000 for the small config) using numeric functions baked into the config resolver. The output goes to a temporary directory and is shared as a dependency by the vendor and rating site generation steps.

Vendors and rating sites are generated per-batch. Each batch introduces ten new vendors and ten new rating sites. Batch 0 therefore contains vendors 0–9 and rating sites 0–9 (20 endpoints total), batch 1 contains 0–19 (40 endpoints total), and so on. The per-source templates receive the provenance IRI of the source being generated (e.g. `http://www.vendor3.fr/`) and the path to the shared product directory, so that offers and reviews can reference the correct products. The output for each source is a single `.nq` file, e.g. `model/dataset/vendor3.nq`.

The Snakemake rule graph for data generation has three rules: `start_generator_container` writes a status file confirming the WatDiv binary is present, `generate_products` produces the product directory, and `generate_vendors` / `generate_ratingsites` fan out across all sources in parallel. The total number of sources is `10 * n_batch` for each type. For the small config with `n_batch=2`, this means 20 vendors and 20 rating sites.

In a plain Python reimplementation, dataset generation is a loop: for each source id, fill in the template, write it to a temp file, call `subprocess.run(["watdiv", "-d", tmpfile, str(scale_factor)])` and capture the output to the appropriate `.nq` file. Products must be generated before vendors and rating sites because those templates reference the product output directory.

**Files & resources:**
- Config: `experiments/bsbm/snakefile/config_small.yaml` — scale factor, batch count, source counts
- Templates: `experiments/bsbm/model/watdiv/{bsbm-product,bsbm-vendor,bsbm-ratingsite}.ttl`
- WatDiv binary: `generators/watdiv/bin/watdiv` (compiled C++, run inside a Docker container)
- Snakefile: `snakemake/generate-data.smk`
- Output data: `experiments/bsbm/model/dataset/{vendor,ratingsite}{N}.nq` and `experiments/bsbm/model/tmp/product/`

---

## 2. Ingestion

Ingestion loads the generated `.nq` files into Virtuoso and then configures one named-graph-backed SPARQL endpoint per federation member. Virtuoso's `SYS_SPARQL_HOST` table lets you register a named graph URI against a distinct host path, making each graph queryable at its own URL. This is what turns a single Virtuoso instance into a simulated federation.

The process has three sequential steps per batch.

First, a Docker Compose scale operation creates one Virtuoso container per batch. Each container runs on the same port (8890 inside) but is exposed on a separate host port. The container naming convention is `docker-bsbm-virtuoso-1`, `docker-bsbm-virtuoso-2`, etc., where the number is `batch_id + 1`.

Second, the data for a given batch is loaded. The data files for batch `b` are all vendor and rating site files whose index falls within that batch's range. For batch 0 that is `vendor0.nq` through `vendor9.nq` and `ratingsite0.nq` through `ratingsite9.nq`; for batch 1 it extends to include the new members. Loading is done via the Virtuoso `isql` utility, either by exec-ing into the container or calling the binary directly. The `virtuoso.py` script wraps this: it calls `DB.DBA.RDF_LOAD_RDFXML_MT` or the equivalent bulk loader through isql to ingest each `.nq` file into its respective named graph.

Third, once data is loaded, a federation endpoint is registered for each member. The `virtuoso.py create-sparql-endpoint` command inserts a row into `DB.DBA.SYS_SPARQL_HOST` via isql. The row maps the federation member's IRI (e.g. `http://www.vendor3.fr/`) to a local path (e.g. `/vendor3/sparql`) on the host. Virtuoso then serves that named graph at `http://localhost:8890/vendor3/sparql`. A JSON mapping file (`virtuoso-proxy-mapping-batch{b}.json`) is written recording the IRI-to-URL correspondence; this file is consumed later by both the query generation and engine evaluation phases.

The proxy mapping file is the key artefact from ingestion. It contains a flat JSON object where each key is a federation member IRI and each value is the actual SPARQL endpoint URL that answers queries about that member. For `config_small.yaml` with `n_batch=2`, the file for batch 1 will have 40 entries covering vendors 0–19 and rating sites 0–19.

In a plain Python reimplementation, ingestion is three steps: (a) start or ensure the Virtuoso containers are running, (b) for each data file for the current batch call the isql loader, and (c) for each federation member call the isql `INSERT INTO DB.DBA.SYS_SPARQL_HOST` statement and record the endpoint in the mapping JSON.

**Files & resources:**
- Config: `experiments/bsbm/snakefile/config_small.yaml` — service name, port, isql path, data dir
- Compose file: `experiments/bsbm/docker/virtuoso.yml` — Virtuoso image and port bindings
- Input data: `experiments/bsbm/model/dataset/*.nq`
- Script: `fedshop/virtuoso.py` — wraps isql bulk-load and endpoint registration commands
- Snakefile: `snakemake/ingest-data.smk`
- Sentinel outputs: `experiments/bsbm/virtuoso-containers-ok.txt`, `virtuoso-data-batch{b}-ok.txt`, `virtuoso-federation-endpoints-batch{b}-ok.txt`
- Artefact output: `experiments/bsbm/virtuoso-proxy-mapping-batch{b}.json` — IRI → SPARQL URL map consumed by query generation and evaluation

---

## 3. Query Generation

Query generation produces concrete, executable SPARQL queries from abstract templates. Each template contains placeholder variables (e.g. `?ProductType`, `?constValue1`) that are replaced with actual values drawn from the dataset. The output is one `injected.sparql` file per (query template, instance id) pair, plus reference result sets and source selection tables used later for correctness checking.

The process has four sequential steps per query template.

**Building the value selection query.** Each template is accompanied by a `.const.json` file that describes which template variables must be filled and any relational constraints between them (e.g. `constValue1 < value1`). The `query.py build-value-selection-query` command reads the template and the constraints file and produces a `value_selection.json` file describing what SPARQL queries need to be executed against the dataset in order to discover valid substitution values. For unconstrained variables the query is a simple `SELECT DISTINCT ?x WHERE { ... }` over the relevant triple pattern; for constrained variables the query includes a FILTER.

**Sampling the workload values.** The `query.py create-workload-value-selection` command fires the value-selection queries against the batch-0 Virtuoso endpoint and collects the results. It then samples `n_query_instances` rows from the result set, applying stratification or random sampling as configured, to produce a `workload_value_selection.csv` file. This CSV has one row per query instance; each row contains the substitution values for all template placeholders.

**Instantiating individual queries.** The `query.py instanciate-workload` command reads the template and one row from the workload CSV and substitutes the placeholder variables with their concrete values, producing the final `injected.sparql`. The substitution rewrites the SPARQL algebra rather than doing naive string replacement: the rdflib SPARQL parser is used to parse the template, the placeholder variables are replaced in the algebra tree, and the modified algebra is serialised back to a SPARQL string. This is what `rdflib_algebra.py` implements. The output is a flat SELECT query with all constants inlined, no named variables in the WHERE clause that are actually constants.

**Executing against the reference endpoint.** The `query.py execute-query` command sends the injected query to the Virtuoso endpoint and writes the result rows as a CSV (`results-batch{b}.csv`). These are the ground-truth results that an engine under evaluation must match. A `composition.json` file is also produced that maps each triple pattern in the query to a canonical name (tp0, tp1, …); this map is consumed during evaluation to align the engine's source selection output with the reference.

In a plain Python reimplementation, query generation is a loop over templates, then over instances. For each template, fire the value selection query against Virtuoso using SPARQLWrapper, sample `n_query_instances` rows, and for each row substitute into the template (either via string replacement or algebra manipulation) and write the injected SPARQL file. Then execute the injected query and save the reference CSV.

**Files & resources:**
- Config: `experiments/bsbm/snakefile/config_small.yaml` — `n_query_instances`, Virtuoso endpoint
- Query templates: `experiments/bsbm/queries/q{N}.sparql` and `q{N}.const.json`
- Running Virtuoso: batch-0 container at `http://localhost:8890/sparql` (used for value sampling and reference execution)
- Script: `fedshop/query.py` — `build-value-selection-query`, `create-workload-value-selection`, `instanciate-workload`, `execute-query`
- Script: `fedshop/algebra/rdflib_algebra.py` — SPARQL algebra manipulation for constant substitution
- Snakefile: `snakemake/generate-queries.smk`
- Intermediate outputs per query template: `benchmark/generation/{query}/value_selection.json`, `workload_value_selection.csv`
- Final outputs per instance: `benchmark/generation/{query}/instance_{i}/injected.sparql`, `composition.json`, `results-batch{b}.csv`

---

## 4. Evaluation

Evaluation runs each engine under test against every (query instance, batch, attempt) combination and collects five output artefacts, then computes federated source-selection metrics.

**Engine adapter protocol.** Every engine is wrapped in a Python adapter script at `fedshop/engines/{engine}.py`. The adapter must implement three CLI commands: `prerequisites` (compile the engine or verify it is ready), `generate-config-file` (produce the engine's federation config for a given batch), and `run-benchmark` (execute a query and write the artefacts).

The federation config maps the federation members' IRIs to their proxy endpoints. The proxy sits at `http://localhost:5555/` and intercepts all SPARQL HTTP traffic from the engine. Before each query run the adapter resets the proxy counters via `GET /reset`; after the run it reads the counters via `GET /get-stats` to learn how many HTTP requests and ASK queries the engine sent and how many bytes were transferred. These numbers go into `stats.csv`.

**Per-run artefacts.** For each combination of (engine, query, instance, batch, attempt) the adapter writes four files under `benchmark/evaluation/{engine}/{query}/instance_{i}/batch_{b}/attempt_{a}/`:

- `results.txt` — the engine's raw result output in whatever format it natively produces.
- `source_selection.txt` — the engine's raw source selection output, typically a list of triple-pattern-to-endpoint assignments.
- `stats.csv` — timing and HTTP metrics: `exec_time`, `source_selection_time`, `planning_time`, `ask` (number of ASK queries), `http_req`, `data_transfer`. If the engine times out or crashes, this file contains the string `timeout` or `error_runtime` in the timing columns.
- `query_plan.txt` — the engine's internal query plan, for debugging.

Two post-processing steps then convert the raw files to canonical CSV format. `transform-results` parses `results.txt` and writes `results.csv` in the same column layout as the reference CSV produced during query generation. `transform-provenance` parses `source_selection.txt` and reshapes it into `provenance.csv`, a matrix with one column per triple pattern (tp0, tp1, …) and one row per result set row showing which endpoint answered that triple pattern for that result.

**Correctness check.** The `evaluate.smk` `transform_results` rule compares `results.csv` against the reference CSV. Both are sorted and compared with pandas `equals`. A mismatch writes `error_mismatch_expected_results` into `stats.csv` rather than aborting the pipeline.

**Metric computation.** The `metrics.py compute-metrics` command aggregates all `provenance.csv` files for a batch into a single metrics CSV. The metrics are computed over the source-selection matrix:

- `nb_results` — number of result rows in `results.csv`.
- `nb_distinct_sources` — number of distinct endpoints appearing anywhere in the provenance matrix.
- `relevant_sources_selectivity` — `nb_distinct_sources` divided by the total number of federation members in this batch.
- `tpwss` (triple-pattern-wise source selection) — sum over all triple patterns of the number of distinct sources that answered that pattern. Measures over-selection: a perfect engine would return exactly one source per triple pattern.
- `avg_rwss`, `min_rwss`, `max_rwss` (result-wise source selection) — for each result row, count the number of distinct sources that contributed to it; then take mean, min, max. Only meaningful when provenance is per-result, not just per-triple-pattern; null in evaluation mode where per-result attribution is unavailable.

The final `metrics.csv` is a join of the metrics and stats data across all engines, queries, instances, batches, and attempts. This is the primary output of the benchmark.

**Early-stop logic.** If a query times out on batch `b`, the evaluation pipeline automatically skips that query on all higher batches for the same engine and instance. The skip is detected by checking whether the `results.txt` for the previous batch is empty (a timed-out run writes an empty file). When a skip occurs the adapter is still called with `--noexec` to create placeholder artefacts with the inherited failure reason.

In a plain Python reimplementation, evaluation is a nested loop: for each engine, check prerequisites, then loop over (query, instance, batch, attempt). For each combination: reset the proxy, call `generate-config-file` to write the engine's endpoint TTL, run the engine subprocess with a timeout, call `transform-results` and `transform-provenance`, write `stats.csv` from proxy counters, check for timeout propagation from prior batches. After all runs, compute metrics by scanning all `provenance.csv` files.

**Files & resources:**
- Config: `experiments/bsbm/snakefile/config_small.yaml` — engine list, attempt count, proxy settings
- Engine adapter: `fedshop/engines/{engine}.py` — implements `prerequisites`, `generate-config-file`, `run-benchmark`, `transform-results`, `transform-provenance`
- Engine config per batch: written by the adapter, e.g. `benchmark/evaluation/{engine}/config_batch{b}.ttl`
- Input query: `benchmark/generation/{query}/instance_{i}/injected.sparql`
- Proxy compose file: `experiments/bsbm/docker/proxy.yml` — FedShop HTTP proxy at `localhost:5555`
- Proxy endpoints: `GET http://localhost:5555/reset` (before each run), `GET http://localhost:5555/get-stats` (after)
- Running Virtuoso: batch-specific container at `http://localhost:8890/sparql`
- Snakefile: `snakemake/evaluate.smk`
- Per-run outputs: `benchmark/evaluation/{engine}/{query}/instance_{i}/batch_{b}/attempt_{a}/results.txt`, `results.csv`, `source_selection.txt`, `provenance.csv`, `stats.csv`, `query_plan.txt`
- Aggregate outputs: `benchmark/evaluation/{engine}/metrics_batch{b}.csv`, `metrics.csv`

---

## Key File Paths

```
experiments/bsbm/
  model/dataset/             # .nq files per federation member
  model/tmp/product/         # shared product data (watdiv output)
  queries/                   # q01.sparql, q01.const.json, ...
  virtuoso-proxy-mapping-batch{b}.json   # IRI → endpoint URL
  benchmark/
    generation/
      {query}/
        value_selection.json
        workload_value_selection.csv
        instance_{i}/
          injected.sparql    # concrete query
          composition.json   # tp name → triple pattern text
          results-batch{b}.csv   # reference results
    evaluation/
      {engine}/
        {engine}-ok.txt      # prerequisites sentinel
        {query}/instance_{i}/batch_{b}/attempt_{a}/
          results.txt        # raw engine output
          results.csv        # normalised results
          source_selection.txt
          provenance.csv     # tp × result source matrix
          stats.csv
          query_plan.txt
      metrics_batch{b}.csv   # merged metrics + stats for one batch
      metrics.csv            # merged across all batches
```
