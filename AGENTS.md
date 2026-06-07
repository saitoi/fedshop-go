# Project Context

This workspace is for preparing FedShop benchmarks and later building a minimal
federated SPARQL query engine in Go.

## Important Paths

- `instructions.md`: original task.
- `reference-papers/fedshop.pdf`: FedShop article.
- `reference-repos/FedShop`: benchmark implementation.
- `reference-repos/query-engines`: current source checkouts for engines and
  support tools.
- `.agents/skills`: project-scoped skills installed for this repository.
- `skills-lock.json`: pinned project skill metadata.
- `scripts`: local wrappers for cloning and running FedShop.
- `docs/fedshop-benchmark.md`: benchmark notes and runbook.

## FedShop Facts

- Default workload: 12 query templates, 10 instances each.
- Default scale: 10 batches, from 20 to 200 federation members.
- Full config: `reference-repos/FedShop/experiments/bsbm/snakefile/config.yaml`.
- Smoke config: `reference-repos/FedShop/experiments/bsbm/snakefile/config_small.yaml`.
- Main evaluation outputs:
  `reference-repos/FedShop/experiments/bsbm/benchmark/evaluation`.

## Engine Notes

- Full FedShop config names `fedx`, `costfed`, `splendid`, `semagrow`,
  `anapsid`, `fedup_id`, `hibiscus`, `fedup`, and `rsa`.
- Current FedX is inside Eclipse RDF4J. FedShop's adapter expects an older
  standalone wrapper jar, so an adapter port is needed before RDF4J can replace
  the FedX submodule path for actual runs.
- `rsa` is a reference-source-assignment baseline implemented through ARQ/Jena
  plus FedUP-generated SERVICE queries.

## Recommended Workflow

1. Refresh source references:
   `scripts/clone-query-engines.sh`
2. Link compatible updated sources into FedShop:
   `scripts/fedshop-link-updated-sources.sh`
3. Build the Docker environment:
   `scripts/fedshop-docker.sh build`
4. Run a small dry-run plan:
   `scripts/fedshop-run.sh smoke`
5. Run filtered benchmarks before the full workload:
   `scripts/fedshop-run.sh evaluate --engine fedup,rsa --query q01 --instance 0 --batch 0 --attempt 0`

Prefer `scripts/fedshop-run.sh` for local runs; it uses `uv run` and does not
depend on a bare `python` command. The default uv dependency file is
`scripts/fedshop-uv-requirements.txt`, a lean runner set that avoids `fasttext`.
The wrapper defaults to Python 3.8 because FedShop's upstream
`environment.yml` declares `python=3.8`; set `FEDSHOP_PYTHON_VERSION` to test
newer runtimes. Use Docker for full query generation, Virtuoso/JVM/system
dependency isolation, and long full benchmark runs.

## Project Skills

Use project-scoped skills from `.agents/skills` when relevant:

- `golang-pro` and `cli-developer` for the Go query engine and its CLI.
- `devops-engineer` for Docker, benchmark reproducibility, and CI.
- `test-master` and `test-driven-development` for Go engine and benchmark tests.
- `systematic-debugging` for benchmark, uv, Docker, and runtime failures.
- `verification-before-completion` before claiming work is done.
- `code-documenter` for runbooks and persistent context.
- `conventional-commit` for commit messages.
- `requesting-code-review` before merging substantial changes.

## Go Engine Direction

Use the cloned engines as references, but keep the first Go implementation
minimal:

- Parse enough SPARQL basic graph patterns for FedShop query templates.
- Use source selection based on endpoint summaries or ASK probes.
- Support SERVICE-query execution against SPARQL endpoints.
- Implement simple bind/hash joins first, then add FedX-style bound joins and
  Semagrow/CostFed-style metadata-aware ordering where feasible.
- Emit FedShop-compatible results, selected sources, stats, and query-plan files
  so a new `fedshop/engines/<go-engine>.py` adapter can benchmark it.
