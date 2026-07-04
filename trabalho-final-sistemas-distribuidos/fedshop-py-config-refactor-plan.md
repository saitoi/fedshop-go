# Simplify and Validate `fedshop-py` Configuration

## Summary

Replace the custom dataclass/OmegaConf-like loader with concise YAML source
configs, Pydantic v2 validation, deterministic Python resolution, and
automatically persisted resolved manifests.

Preserve upstream FedShop configs unchanged. Add independent
`fedshop-py/configs/smoke.yaml` and `fedshop-py/configs/full.yaml`. Do not use
`BaseSettings` or environment-variable overrides.

## Key Changes

- Add `pydantic>=2` and replace the dataclasses in `fedshop.config` with:
  - Source models for human-authored YAML.
  - A fully resolved `BenchmarkConfig` returned by `load_config()`.
  - Strict validation using `extra="forbid"` and appropriate positive-number,
    path, and engine constraints.
- Use a concise source schema:
  - Root: `profile`, `seed`, and `use_docker`.
  - Generation: `workdir`, `batches`, `query_instances`,
    `members_per_batch`, `product_count`, optional generator/Virtuoso
    settings, and per-section WatDiv parameter overrides.
  - Evaluation: `attempts`, `timeout_seconds`, proxy settings, and engine
    definitions.
- Keep canonical WatDiv template parameters and service defaults in Python.
  Port the active upstream product hierarchy, producer, feature,
  normal-distribution, and truncated-distribution calculations using a local,
  seeded random-number generator. Apply YAML overrides after calculating
  defaults.
- Resolve stochastic and derived values once while loading. Never recompute
  random values from model properties.
- Derive the following in Python:
  - Total vendor and ratingsite counts.
  - Cumulative members for every batch.
  - Batch IRIs and federation-member mappings.
  - Dataset filenames.
  - Generator, template, dataset, compose, engine, endpoint, and proxy values.
- Resolve relative paths from the workspace root discovered through the
  repository marker. Add:

  ```python
  load_config(path, *, workspace_root=None)
  ```

  This permits tests and embedded callers to supply an explicit root. Return
  normalized absolute `Path` values internally.
- Make a clean break from the legacy format:
  - Reject `${...}` interpolation with a targeted migration error.
  - Do not accept the legacy expanded/OmegaConf schema.
  - Update `fedshop-py` consumers to readable names such as `batches`,
    `query_instances`, `attempts`, and `timeout_seconds`.
- Preserve `reference-repos/FedShop/**/config*.yaml`, because upstream
  Snakemake still consumes them.
- Change the `fedshop-py` CLI default to `fedshop-py/configs/smoke.yaml` and
  document selecting `full.yaml`.
- Keep benchmark configuration in YAML. Retain existing CLI arguments for
  runtime selections and output locations. Add no environment configuration
  layer or generic `--set` mechanism.
- Automatically write `resolved-config.yaml` whenever a command produces
  artifacts:
  - Generation commands: selected generation/work directory.
  - Query and evaluation commands: benchmark directory.
  - Ingestion: generation work directory.
  - Metrics: output file's parent directory.
- Include the source path, seed, normalized paths, resolved WatDiv parameters,
  federation members, endpoints, and engine configuration in the manifest.
  Emit stable key ordering.
- Update the benchmark runbook with the new schema, smoke/full examples, path
  rules, override syntax, manifest purpose, and legacy-config rejection.

## Implementation Sequence

Follow red-green-refactor for each behavior:

1. Add failing model-validation and concise-config loading tests, then
   introduce Pydantic source models.
2. Add failing deterministic-resolution tests, then implement seeded upstream
   calculations and derived federation data.
3. Add failing path-resolution and legacy-rejection tests, then replace the
   current resolver loader.
4. Add failing consumer tests using the renamed API, then migrate generation,
   ingestion, query, evaluation, metrics, and engine adapters.
5. Add failing manifest and CLI tests, then implement automatic manifest
   persistence and switch the CLI default.
6. Replace the `fedshop-py` fixture, add smoke/full configs, update
   documentation, and run the complete suite.

## Test Plan

- Both new configs validate and load. Smoke resolves two batches and two query
  instances; full resolves ten batches and ten query instances.
- Smoke batch 0 contains 10 vendors plus 10 ratingsites; batch 1 contains 20
  plus 20. Full batch 9 contains 100 plus 100.
- Repeated loads with the same seed produce identical parameters and
  manifests. A different seed changes stochastic values without changing
  topology.
- WatDiv defaults match upstream calculation rules, while section overrides
  replace only the named values.
- Workspace-relative paths resolve identically regardless of the process
  working directory.
- Missing required sections, unknown keys, invalid counts, unsupported engine
  options, and `${...}` values produce actionable validation errors.
- Every artifact-producing CLI path writes a complete, reloadable
  `resolved-config.yaml`.
- Existing generation, ingestion, query, evaluation, metrics, and
  engine-adapter tests pass after migration.
- Run `uv run pytest` from `fedshop-py` as final verification.

## Assumptions

- This is a clean break for `fedshop-py` configuration only; upstream
  FedShop/Snakemake remains untouched.
- Python defaults mirror the active full upstream configuration.
  `smoke.yaml` contains only the scale and workload overrides needed for the
  smaller run.
- Pydantic `BaseModel`, not `BaseSettings`, owns configuration validation.
- There is no environment-variable precedence or new generic CLI override
  mechanism.
- A resolved manifest may overwrite an existing manifest in the same artifact
  directory because an identical source configuration and seed must resolve
  identically.
