"""FedShop CLI — top-level entry point with phase sub-groups."""

from __future__ import annotations

import glob
from pathlib import Path

import click

DEFAULT_CONFIG = "experiments/bsbm/snakefile/config_small.yaml"
DEFAULT_BENCH_DIR = "experiments/bsbm/benchmark"


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
    workdir = cfg.generation.workdir
    templates_dir = Path(workdir) / "queries"
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
        generate_queries_for_template(
            template_path=template_path,
            const_path=const_path,
            output_dir=q_output_dir,
            config=cfg,
            batch_id=batch_id,
        )
        click.echo(f"Generated queries for {template_path.stem}")


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
    from .engines.fedx import FedXAdapter
    from .engines.pyfedx import PyFedXAdapter
    cfg = _load(config)
    adapters = {"fedx": FedXAdapter, "pyfedx": PyFedXAdapter, "costfed": CostFedAdapter}
    if engine not in adapters:
        raise click.ClickException(f"Unknown engine: {engine}")
    adapters[engine](cfg).prerequisites()


@evaluate.command("generate-config")
@click.argument("engine")
@click.argument("batch_id", type=int)
@click.option("--config", default=DEFAULT_CONFIG, show_default=True)
def evaluate_generate_config(engine, batch_id, config):
    """Write federation config file for ENGINE at BATCH_ID."""
    import json
    from .engines.costfed import CostFedAdapter
    from .engines.fedx import FedXAdapter
    from .engines.pyfedx import PyFedXAdapter
    cfg = _load(config)
    mapping_file = Path(cfg.generation.workdir) / f"virtuoso-proxy-mapping-batch{batch_id}.json"
    proxy_mapping = json.loads(mapping_file.read_text()) if mapping_file.exists() else {}
    adapters = {"fedx": FedXAdapter, "pyfedx": PyFedXAdapter, "costfed": CostFedAdapter}
    path = adapters[engine](cfg).generate_config_file(batch_id, proxy_mapping)
    click.echo(f"Config written to {path}")


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
def evaluate_run_all(config, bench_dir, engine_filter, query_filter):
    """Run all (engine, query, instance, batch, attempt) combinations."""
    from .evaluate import run_all_evaluations
    cfg = _load(config)
    run_all_evaluations(
        config=cfg,
        bench_dir=Path(bench_dir),
        engine_filter=engine_filter,
        query_filter=query_filter,
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
        provenance_files = sorted(glob.glob(f"{bench_dir}/evaluation/**/provenance.csv", recursive=True))

    if not provenance_files:
        raise click.ClickException("No provenance files found.")

    df = compute_metrics(cfg, list(provenance_files), outfile)
    click.echo(f"Metrics written to {outfile} ({len(df)} rows)")
