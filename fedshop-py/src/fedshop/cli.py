"""FedShop CLI — top-level entry point with phase sub-groups."""

from __future__ import annotations

import glob
from pathlib import Path

import click

_FEDSHOP_PY_DIR = Path(__file__).parent.parent.parent  # src/fedshop/ → src/ → fedshop-py/
DEFAULT_CONFIG = str(_FEDSHOP_PY_DIR / "config/config_small.yaml")
DEFAULT_BENCH_DIR = str(_FEDSHOP_PY_DIR / "benchmark")


def _load(config_path: str):
    from .config import load_config
    return load_config(config_path)


# ─── Top-level group ────────────────────────────────────────────────────────

@click.group()
def cli():
    """FedShop benchmark pipeline (uv-native Python reimplementation)."""


# ─── Phase 1: generate ──────────────────────────────────────────────────────

@cli.group()
def generate():
    """Phase 1: dataset generation via WatDiv."""


@generate.command("products")
@click.option("--config", default=DEFAULT_CONFIG, show_default=True)
@click.option("--output-dir", default=None)
def generate_products_cmd(config, output_dir):
    """Generate the shared product dataset."""
    from .generate import generate_products
    cfg = _load(config)
    out = Path(output_dir) if output_dir else Path(cfg.generation.schema["product"].export_output_dir)
    generate_products(cfg, out)
    click.echo(f"Products written to {out}")


@generate.command("sources")
@click.option("--config", default=DEFAULT_CONFIG, show_default=True)
@click.option("--section", type=click.Choice(["vendor", "ratingsite"]), default=None)
@click.option("--id", "source_id", type=int, default=None)
def generate_sources_cmd(config, section, source_id):
    """Generate vendor/ratingsite .nq files. Without --id generates all."""
    from .generate import generate_all_sources, generate_source
    cfg = _load(config)

    if section and source_id is not None:
        schema = cfg.generation.schema[section]
        output_file = Path(schema.export_output_dir) / f"{section}{source_id}.nq"
        generate_source(cfg, section, source_id, output_file)
        click.echo(f"Generated {output_file}")
    else:
        generate_all_sources(cfg)
        click.echo("All sources generated.")


# ─── Phase 2: ingest ────────────────────────────────────────────────────────

@cli.group()
def ingest():
    """Phase 2: load .nq files into Virtuoso and register SPARQL endpoints."""


@ingest.command("batch")
@click.argument("batch_id", type=int)
@click.option("--config", default=DEFAULT_CONFIG, show_default=True)
def ingest_batch_cmd(batch_id, config):
    """Ingest data for BATCH_ID and write proxy mapping JSON."""
    from .ingest import ingest_batch
    cfg = _load(config)
    mapping_file = ingest_batch(cfg, batch_id)
    click.echo(f"Proxy mapping written to {mapping_file}")


# ─── Phase 3: query ─────────────────────────────────────────────────────────

@cli.group()
def query():
    """Phase 3: query generation (value selection, instantiation, reference execution)."""


@query.command("run-all")
@click.option("--config", default=DEFAULT_CONFIG, show_default=True)
@click.option("--bench-dir", default=DEFAULT_BENCH_DIR, show_default=True)
@click.option("--batch-id", type=int, default=0)
@click.option("--query-name", default=None, help="Restrict to one query template.")
def query_run_all(config, bench_dir, batch_id, query_name):
    """Generate queries for all templates (value selection → instantiation → reference exec)."""
    import os
    cfg = _load(config)
    templates_dir = Path(cfg.generation.queries_dir)
    output_dir = Path(bench_dir) / "generation"

    templates = sorted(templates_dir.glob("q*.sparql"))
    if query_name:
        templates = [t for t in templates if t.stem == query_name]

    from .query import generate_queries_for_template

    endpoint = cfg.generation.virtuoso.default_endpoint
    for template_path in templates:
        const_path = template_path.with_suffix(".const.json")
        if not const_path.exists():
            click.echo(f"Skipping {template_path.stem}: no .const.json", err=True)
            continue
        q_output_dir = output_dir / template_path.stem
        q_output_dir.mkdir(parents=True, exist_ok=True)
        try:
            generate_queries_for_template(
                template_path=template_path,
                const_path=const_path,
                output_dir=q_output_dir,
                config=cfg,
                batch_id=batch_id,
            )
            click.echo(f"Generated queries for {template_path.stem}")
        except Exception as exc:
            click.echo(f"Warning: skipping {template_path.stem} (batch {batch_id}): {exc}", err=True)


# ─── Phase 4: evaluate ──────────────────────────────────────────────────────

@cli.group()
def evaluate():
    """Phase 4: engine evaluation."""


@evaluate.command("prerequisites")
@click.argument("engine")
@click.option("--config", default=DEFAULT_CONFIG, show_default=True)
def evaluate_prerequisites(engine, config):
    """Check/compile prerequisites for ENGINE."""
    from .engines.costfed import CostFedAdapter
    from .engines.fedshop_go import FedShopGoAdapter
    from .engines.fedx import FedXAdapter
    from .engines.pyfedx import PyFedXAdapter
    from .engines.semagrow import SemagrowAdapter
    from .engines.splendid import SplendidAdapter
    cfg = _load(config)
    adapters = {
        "fedx": FedXAdapter,
        "pyfedx": PyFedXAdapter,
        "costfed": CostFedAdapter,
        "fedshop-go": FedShopGoAdapter,
        "semagrow": SemagrowAdapter,
        "splendid": SplendidAdapter,
    }
    if engine not in adapters:
        click.echo(f"Warning: no adapter for engine '{engine}', skipping prerequisites.", err=True)
        return
    adapters[engine](cfg).prerequisites()


@evaluate.command("generate-config")
@click.argument("engine")
@click.argument("batch_id", type=int)
@click.option("--config", default=DEFAULT_CONFIG, show_default=True)
def evaluate_generate_config(engine, batch_id, config):
    """Write federation config file for ENGINE at BATCH_ID."""
    import json
    from .engines.costfed import CostFedAdapter
    from .engines.fedshop_go import FedShopGoAdapter
    from .engines.fedx import FedXAdapter
    from .engines.pyfedx import PyFedXAdapter
    from .engines.rsa import RsaAdapter
    from .engines.semagrow import SemagrowAdapter
    from .engines.splendid import SplendidAdapter
    cfg = _load(config)
    mapping_file = Path(cfg.generation.workdir) / f"virtuoso-proxy-mapping-batch{batch_id}.json"
    proxy_mapping = json.loads(mapping_file.read_text()) if mapping_file.exists() else {}
    adapters = {
        "fedx": FedXAdapter,
        "pyfedx": PyFedXAdapter,
        "costfed": CostFedAdapter,
        "fedshop-go": FedShopGoAdapter,
        "rsa": RsaAdapter,
        "semagrow": SemagrowAdapter,
        "splendid": SplendidAdapter,
    }
    path = adapters[engine](cfg).generate_config_file(batch_id, proxy_mapping)
    click.echo(f"Config written to {path}")


@evaluate.command("build-summary")
@click.argument("batch_id", type=int)
@click.option("--config", default=DEFAULT_CONFIG, show_default=True)
def evaluate_build_summary(batch_id, config):
    """Build the measured fedshop-go endpoint summary for BATCH_ID."""
    from .engines.fedshop_go import FedShopGoAdapter
    path = FedShopGoAdapter(_load(config)).build_summary(batch_id)
    click.echo(f"Summary written to {path}")


@evaluate.command("run")
@click.argument("engine")
@click.argument("query_name")
@click.argument("instance_id", type=int)
@click.argument("batch_id", type=int)
@click.argument("attempt", type=int)
@click.option("--config", default=DEFAULT_CONFIG, show_default=True)
@click.option("--bench-dir", default=DEFAULT_BENCH_DIR, show_default=True)
@click.option("--noexec", is_flag=True, default=False)
def evaluate_run(engine, query_name, instance_id, batch_id, attempt, config, bench_dir, noexec):
    """Run a single (engine, query, instance, batch, attempt) evaluation."""
    from .evaluate import run_evaluation
    cfg = _load(config)
    stats = run_evaluation(
        config=cfg,
        engine_name=engine,
        query_name=query_name,
        instance_id=instance_id,
        batch_id=batch_id,
        attempt=attempt,
        bench_dir=Path(bench_dir),
        noexec=noexec,
    )
    click.echo(f"Stats written to {stats}")


@evaluate.command("run-all")
@click.option("--config", default=DEFAULT_CONFIG, show_default=True)
@click.option("--bench-dir", default=DEFAULT_BENCH_DIR, show_default=True)
@click.option("--engine", "engine_filter", default=None)
@click.option("--query", "query_filter", default=None)
@click.option("--skip-existing-ok", is_flag=True, default=False, help="Skip cases whose stats.csv is already numeric or timeout.")
def evaluate_run_all(config, bench_dir, engine_filter, query_filter, skip_existing_ok):
    """Run all (engine, query, instance, batch, attempt) combinations."""
    from .evaluate import run_all_evaluations
    cfg = _load(config)
    run_all_evaluations(
        config=cfg,
        bench_dir=Path(bench_dir),
        engine_filter=engine_filter,
        query_filter=query_filter,
        skip_existing_ok=skip_existing_ok,
    )


# ─── Metrics ────────────────────────────────────────────────────────────────

@cli.group()
def metrics():
    """Compute benchmark metrics from provenance CSV files."""


@metrics.command("compute")
@click.argument("outfile")
@click.argument("provenance_files", nargs=-1)
@click.option("--config", default=DEFAULT_CONFIG, show_default=True)
@click.option("--bench-dir", default=DEFAULT_BENCH_DIR, show_default=True)
def metrics_compute(outfile, provenance_files, config, bench_dir):
    """Compute metrics from PROVENANCE_FILES (or auto-discover from bench-dir)."""
    from .metrics import compute_metrics
    cfg = _load(config)

    if not provenance_files:
        from .metrics import compute_full_metrics
        df = compute_full_metrics(cfg, Path(bench_dir), outfile)
        click.echo(f"Metrics written to {outfile} ({len(df)} rows)")
        return

    df = compute_metrics(cfg, list(provenance_files), outfile)
    click.echo(f"Metrics written to {outfile} ({len(df)} rows)")


@metrics.command("typst-tables")
@click.argument("outfile")
@click.option("--config", default=DEFAULT_CONFIG, show_default=True)
@click.option("--bench-dir", default=DEFAULT_BENCH_DIR, show_default=True)
@click.option("--from-csv", default=None, help="Read from existing metrics CSV instead of recomputing.")
@click.option("--hypothesis-csv", default=None, help="Include hypothesis-test CSV as a Typst table.")
@click.option(
    "--mode",
    type=click.Choice(["all", "timing", "summary", "correctness", "source-selection", "query-performance", "hypothesis"]),
    default="all",
    show_default=True,
    help="Which Typst table(s) to render.",
)
@click.option("--decimals", type=int, default=2, show_default=True, help="Decimal places for numeric values.")
@click.option("--batch-id", type=int, default=1, show_default=True, help="Batch used by the per-query performance table.")
@click.option("--hypothesis-top-n", type=int, default=8, show_default=True, help="Maximum hypothesis rows, ranked by median difference.")
@click.option(
    "--attempt-policy",
    type=click.Choice(["all", "primary"]),
    default="all",
    show_default=True,
    help="Aggregate all attempts or only attempt 0.",
)
@click.option("--alpha", default=0.05, show_default=True, type=float, help="Significance level used in the hypothesis caption.")
def metrics_typst_tables(outfile, config, bench_dir, from_csv, hypothesis_csv, mode, decimals, batch_id, hypothesis_top_n, attempt_policy, alpha):
    """Render publication-ready Typst tables from full metrics."""
    from .typst_tables import apply_attempt_policy, read_hypothesis, render

    df = _load_metrics_df(config, bench_dir, from_csv)
    df = apply_attempt_policy(df, attempt_policy)
    hypothesis_df = read_hypothesis(Path(hypothesis_csv)) if hypothesis_csv else None
    if mode == "hypothesis" and hypothesis_df is None:
        raise click.ClickException("--hypothesis-csv is required when --mode hypothesis")
    output_path = Path(outfile)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render(
            df,
            mode,
            decimals,
            batch_id=batch_id,
            hypothesis_df=hypothesis_df,
            alpha=alpha,
            hypothesis_top_n=hypothesis_top_n,
        )
    )
    click.echo(f"Typst tables written to {output_path}")


def _load_metrics_df(config: str, bench_dir: str, from_csv: str | None):
    """Return the full metrics DataFrame, either from a CSV or by recomputing."""
    import tempfile
    if from_csv:
        import pandas as pd
        return pd.read_csv(from_csv)
    cfg = _load(config)
    from .metrics import compute_full_metrics
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        tmp = f.name
    return compute_full_metrics(cfg, Path(bench_dir), tmp)


def _print_table(df, output: str | None):
    """Print DataFrame as aligned text table, optionally saving to CSV."""
    import pandas as pd
    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)
    pd.set_option("display.float_format", "{:.4f}".format)
    click.echo(df.to_string(index=False))
    if output:
        df.to_csv(output, index=False)
        click.echo(f"\nSaved to {output}", err=True)


_ID_COLS = ["engine", "query", "instance", "batch", "attempt", "status"]

_CORRECTNESS_COLS = [
    "nb_results", "nb_ref_results", "mismatch",
    "precision", "recall", "f1",
    "nb_spurious", "nb_missing", "nb_duplicates", "missing_vars",
]

_SOURCE_SEL_COLS = [
    "nb_distinct_sources", "relevant_sources_selectivity",
    "tpwss", "avg_rwss", "min_rwss", "max_rwss",
]


@metrics.command("correctness")
@click.option("--config", default=DEFAULT_CONFIG, show_default=True)
@click.option("--bench-dir", default=DEFAULT_BENCH_DIR, show_default=True)
@click.option("--from-csv", default=None, help="Read from existing metrics CSV instead of recomputing.")
@click.option("--output", default=None, help="Also save the table to this CSV path.")
@click.option("--engine", "engine_filter", default=None, help="Filter to a specific engine.")
@click.option("--query", "query_filter", default=None, help="Filter to a specific query.")
def metrics_correctness(config, bench_dir, from_csv, output, engine_filter, query_filter):
    """Print correctness table: precision, recall, f1, spurious/missing rows, duplicates, missing vars."""
    df = _load_metrics_df(config, bench_dir, from_csv)
    if engine_filter:
        df = df[df["engine"] == engine_filter]
    if query_filter:
        df = df[df["query"] == query_filter]
    cols = [c for c in _ID_COLS if c in df.columns] + [c for c in _CORRECTNESS_COLS if c in df.columns]
    df = df[cols].sort_values([c for c in ["engine", "query", "batch", "instance"] if c in df.columns])
    _print_table(df, output)


@metrics.command("hypothesis-test")
@click.option("--config", default=DEFAULT_CONFIG, show_default=True)
@click.option("--bench-dir", default=DEFAULT_BENCH_DIR, show_default=True)
@click.option("--from-csv", default=None, help="Read from existing metrics CSV instead of recomputing.")
@click.option("--output", default=None, help="Also save the results table to this CSV path.")
@click.option("--target-engine", default="fedshop-go", show_default=True, help="Focal engine for Wilcoxon comparisons.")
@click.option("--alpha", default=0.05, show_default=True, type=float, help="Significance level.")
@click.option("--skip-friedman", is_flag=True, default=False, help="Skip Friedman test (useful when < 3 engines).")
@click.option("--engine", "engine_filter", default=None, help="Keep only rows matching this engine (applied before tests).")
@click.option("--query", "query_filter", default=None, help="Keep only rows matching this query (applied before tests).")
def metrics_hypothesis_test(config, bench_dir, from_csv, output, target_engine, alpha, skip_friedman, engine_filter, query_filter):
    """Run statistical hypothesis tests comparing engines.

    \b
    Wilcoxon signed-rank  — target_engine vs each other engine, paired by
                             (query, instance, batch). Holm correction applied
                             across engines per metric.
    Friedman              — all engines together per metric (blocked by same key).
    Spearman ρ            — batch_id vs metric per engine (scalability).
    """
    from .hypothesis import run_hypothesis_tests
    df = _load_metrics_df(config, bench_dir, from_csv)
    if engine_filter:
        df = df[df["engine"].isin([target_engine, engine_filter])]
    if query_filter:
        df = df[df["query"] == query_filter]
    results = run_hypothesis_tests(
        df,
        target_engine=target_engine,
        alpha=alpha,
        skip_friedman=skip_friedman,
    )
    if results.empty:
        click.echo("No results — not enough paired observations.", err=True)
        return
    _print_table(results, output)


@metrics.command("source-selection")
@click.option("--config", default=DEFAULT_CONFIG, show_default=True)
@click.option("--bench-dir", default=DEFAULT_BENCH_DIR, show_default=True)
@click.option("--from-csv", default=None, help="Read from existing metrics CSV instead of recomputing.")
@click.option("--output", default=None, help="Also save the table to this CSV path.")
@click.option("--engine", "engine_filter", default=None, help="Filter to a specific engine.")
@click.option("--query", "query_filter", default=None, help="Filter to a specific query.")
def metrics_source_selection(config, bench_dir, from_csv, output, engine_filter, query_filter):
    """Print source-selection table: distinct sources, selectivity, tpwss, rwss stats."""
    df = _load_metrics_df(config, bench_dir, from_csv)
    if engine_filter:
        df = df[df["engine"] == engine_filter]
    if query_filter:
        df = df[df["query"] == query_filter]
    cols = [c for c in _ID_COLS if c in df.columns] + [c for c in _SOURCE_SEL_COLS if c in df.columns]
    df = df[cols].sort_values([c for c in ["engine", "query", "batch", "instance"] if c in df.columns])
    _print_table(df, output)


@metrics.command("plot-pr")
@click.option("--config", default=DEFAULT_CONFIG, show_default=True)
@click.option("--bench-dir", default=DEFAULT_BENCH_DIR, show_default=True)
@click.option("--from-csv", default=None, help="Read from existing metrics CSV instead of recomputing.")
@click.option("--output", default=None, help="Save figure to this path (PNG/PDF/SVG). If omitted, opens a window.")
@click.option("--engine", "engine_filter", default=None, help="Filter to a specific engine.")
@click.option("--query", "query_filter", default=None, help="Filter to a specific query.")
@click.option("--title", default="Precision × Recall", show_default=True)
@click.option("--annotate", is_flag=True, default=False, help="Label each point with its query name.")
@click.option("--f1-levels", default="0.25,0.5,0.75", show_default=True,
              help="Comma-separated F1 iso-curve levels to draw.")
def metrics_plot_pr(config, bench_dir, from_csv, output, engine_filter, query_filter, title, annotate, f1_levels):
    """Plot precision vs recall with filled area under the curve per engine.

    Each point is one (engine, query, instance, batch) observation. Points are
    sorted by recall and connected; the area below is filled. F1 iso-curves are
    drawn as dashed reference lines.
    """
    from .plot import plot_precision_recall
    df = _load_metrics_df(config, bench_dir, from_csv)
    if engine_filter:
        df = df[df["engine"] == engine_filter]
    if query_filter:
        df = df[df["query"] == query_filter]
    levels = [float(x.strip()) for x in f1_levels.split(",") if x.strip()]
    try:
        plot_precision_recall(df, output=output, title=title, f1_levels=levels, annotate_queries=annotate)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)
    if output:
        click.echo(f"Plot saved to {output}")
