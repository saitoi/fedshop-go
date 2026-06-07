# FedShop Benchmark Notes

FedShop is under `reference-repos/FedShop`. The local paper is
`reference-papers/fedshop.pdf`.

## Benchmark Shape

FedShop's default BSBM experiment uses:

- 12 query templates: `q01` through `q12`.
- 10 instantiated query instances per template.
- 10 federation batches: batch `0` starts with 10 vendors plus 10 rating sites,
  then each batch adds 10 vendors plus 10 rating sites, up to 200 endpoints.
- Multiple attempts per query/engine/batch/instance. The checked-in full config
  currently sets `evaluation.n_attempts: 3`; the paper/notebook results may use a
  different attempt count, so check the config before comparing numbers.
- Engines in the full config: `fedx`, `costfed`, `splendid`, `semagrow`,
  `anapsid`, `fedup_id`, `hibiscus`, `fedup`, and `rsa`.

The small config at `experiments/bsbm/snakefile/config_small.yaml` is only a
smoke profile: 2 batches, 2 instances, and only `fedx` plus `rsa` enabled.

## Source Repositories

Updated/current source references are cloned under
`reference-repos/query-engines`:

- `rdf4j-fedx`: Eclipse RDF4J, where current FedX is maintained.
- `CostFed`: upstream CostFed.
- `semagrow`: SemaGrow.
- `splendid-server`: SPLENDID server fork maintained by Semagrow.
- `anapsid`: ANAPSID.
- `fedup`: FedUP.
- `sevod-scraper`, `watdiv`, and `FedShop-proxy`: FedShop support tools.

Run this to refresh them:

```bash
scripts/clone-query-engines.sh
```

Run this to symlink structurally compatible updated sources into FedShop's
expected paths:

```bash
scripts/fedshop-link-updated-sources.sh
```

FedX is intentionally not linked by that script. FedShop's adapter expects a
standalone wrapper with `org.example.FedX` and `target/FedX-1.0-SNAPSHOT.jar`;
current FedX is inside RDF4J and needs an adapter port before it can replace the
old FedShop submodule path.

## Running

The local wrappers use `uv run` instead of relying on a bare `python` command.
By default they install the lean runner dependencies from
`scripts/fedshop-uv-requirements.txt`; this avoids FedShop's `fasttext`
dependency during simple FedX/Snakemake runs. The wrapper defaults to Python
3.8 because FedShop declares `python=3.8` in `environment.yml`; override with
`FEDSHOP_PYTHON_VERSION=3.11` if testing a newer runtime. Docker remains useful
for Virtuoso/JVM/system dependencies and long full runs.

Build the FedShop image:

```bash
scripts/fedshop-docker.sh build
```

Open a shell in the image:

```bash
scripts/fedshop-docker.sh shell
```

From inside the image, run a dry-run smoke plan:

```bash
/workspace/scripts/fedshop-run.sh smoke
```

If running from a host with `uv`, use:

```bash
scripts/fedshop-run.sh generate-data --config experiments/bsbm/snakefile/config.yaml --cores 1
scripts/fedshop-run.sh generate-queries --config experiments/bsbm/snakefile/config.yaml --cores 1
scripts/fedshop-run.sh evaluate --config experiments/bsbm/snakefile/config.yaml --cores 1 --rerun-incomplete
```

Filtered examples:

```bash
scripts/fedshop-run.sh evaluate --engine fedup,rsa --query q01 --instance 0 --batch 0 --attempt 0
scripts/fedshop-run.sh evaluate --engine costfed --query q01,q02 --batch 0,1 --rerun-incomplete
```

For commands that need FedShop's full query-generation stack, set:

```bash
FEDSHOP_UV_REQUIREMENTS=reference-repos/FedShop/requirements.txt scripts/fedshop-run.sh generate-queries
```

On hosts without `crypt.h`, the full requirements may fail while building
`fasttext`; use the Docker environment for that path.

## Outputs

Generation outputs go under:

```text
reference-repos/FedShop/experiments/bsbm/benchmark/generation
```

Evaluation outputs and metrics go under:

```text
reference-repos/FedShop/experiments/bsbm/benchmark/evaluation
```

The merged evaluation metrics file is:

```text
reference-repos/FedShop/experiments/bsbm/benchmark/evaluation/metrics.csv
```
