# Local Skills

## Project-Scoped Installed Skills

Installed under `.agents/skills` and pinned in `skills-lock.json`:

- `golang-pro`: use for the planned minimal Go federated query engine, Go project structure, concurrency, performance, and table-driven tests.
- `cli-developer`: use for the Go engine CLI and FedShop-compatible command surfaces.
- `devops-engineer`: use for Docker, reproducible benchmark environments, CI, and system dependency runbooks.
- `test-master`: use for test strategy, integration tests, performance tests, and benchmark validation.
- `code-documenter`: use for AGENTS.md, benchmark runbooks, API docs, and user/developer guides.
- `conventional-commit`: use for standardized Conventional Commit messages before committing project changes.
- `systematic-debugging`: use for failed benchmark runs, uv/Docker setup problems, engine runtime errors, and test failures.
- `test-driven-development`: use before implementing Go engine features or bug fixes.
- `verification-before-completion`: use before declaring benchmark setup, scripts, or engine changes complete.
- `requesting-code-review`: use before merging substantial benchmark or engine work.

Discovery notes:

- `jeffallan/claude-skills` was selected for Go/CLI/DevOps/testing/docs. It has >1K installs for relevant skills and a high-star GitHub repo.
- `obra/superpowers` was selected for workflow skills. The leaderboard shows strong adoption, and installed skills were Low Risk in the CLI audit.
- Docker/benchmark-specific search results had very low install counts and were not installed.
- AI paper reproduction skills were not installed because their own descriptions target deep-learning repositories, while this project is RDF/SPARQL benchmark work.
- `jeffallan/claude-skills@code-reviewer` was installed initially but removed because the Skills CLI reported Snyk High Risk. Use `requesting-code-review` plus the built-in review stance instead.
- `github/awesome-copilot@conventional-commit` was installed on request for commit message generation. It was Low Risk in the CLI audit.

## FedShop Benchmark Prep

Use this checklist when returning to the FedShop work:

1. Read `docs/fedshop-benchmark.md`.
2. Check `git status --short`; this workspace may contain large untracked
   reference repositories.
3. Refresh sources only when needed with `scripts/clone-query-engines.sh`.
4. Use `scripts/fedshop-run.sh --help` for benchmark commands.
5. Before changing FedShop adapters, read the matching file in
   `reference-repos/FedShop/fedshop/engines`.

## Minimal Go Federation Engine

Implementation should start small and stay compatible with FedShop outputs:

- CLI accepts a SPARQL query file, endpoint list/config, output result path,
  source-selection path, stats path, and query-plan path.
- First source selector can be predicate-based from summaries or ASK-based.
- First planner can decompose by triple pattern and use left-deep joins.
- First executor can query endpoints over HTTP SPARQL and join bindings locally.
- Add FedShop adapter only after the CLI can run one query outside Snakemake.
