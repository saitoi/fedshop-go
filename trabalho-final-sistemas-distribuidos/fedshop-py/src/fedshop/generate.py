from __future__ import annotations

import re
from pathlib import Path

from .config import BenchmarkConfig
from .watdiv import run as watdiv_run


def generate_source(
    config: BenchmarkConfig,
    section: str,
    source_id: int,
    output_file: Path,
    product_dir: Path | None = None,
) -> Path:
    """Fill WatDiv template placeholders for one federation member and run WatDiv.

    Returns the path to the generated .nq file.
    """
    gen = config.generation
    schema = gen.schema[section]

    with open(schema.template) as f:
        template = f.read()

    params = dict(schema.params)
    for param, value in params.items():
        template = re.sub(re.escape(f"{{%{param}}}"), str(value), template)

    source_name = f"{section}{source_id}"
    provenance = re.sub(re.escape(f"{{%{section}_id}}"), source_name, schema.provenance)

    model_text = re.sub(re.escape("{%provenance}"), provenance, template)
    model_text = re.sub(re.escape(f"{{%{section}_id}}"), source_name, model_text)
    model_text = re.sub(re.escape("{%export_output_dir}"), schema.export_output_dir, model_text)
    if schema.export_dep_output_dir is not None:
        model_text = re.sub(re.escape("{%export_dep_output_dir}"), schema.export_dep_output_dir, model_text)

    model_file = output_file.parent / f"{source_name}.txt.tmp"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text(model_text)

    scale_factor = int(schema.scale_factor)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w") as output:
        watdiv_run(model_text, scale_factor, output)

    _persist_source_rdf(config, section, source_name, provenance, output_file)
    return output_file


def generate_products(config: BenchmarkConfig, output_dir: Path) -> Path:
    """Generate the shared product dataset.

    Products are federation-agnostic and generated once.
    Returns the output directory.
    """
    gen = config.generation
    schema = gen.schema["product"]

    with open(schema.template) as f:
        template = f.read()

    params = dict(schema.params)
    for param, value in params.items():
        template = re.sub(re.escape(f"{{%{param}}}"), str(value), template)

    template = re.sub(re.escape("{%provenance}"), str(schema.provenance), template)
    template = re.sub(re.escape("{%export_output_dir}"), str(output_dir), template)

    model_file = output_dir / "product.txt.tmp"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text(template)

    scale_factor = int(schema.scale_factor)
    watdiv_run(template, scale_factor, output_dir)

    return output_dir


def generate_all_sources(config: BenchmarkConfig) -> None:
    """Generate all vendor and ratingsite .nq files for all batches.

    Products are generated first (vendors and ratingsites depend on them).
    """
    gen = config.generation
    workdir = Path(gen.workdir)
    product_dir = Path(gen.schema["product"].export_output_dir)
    dataset_dir = Path(gen.schema["vendor"].export_output_dir)

    generate_products(config, product_dir)

    total = int(gen.schema["vendor"].params.get("vendor_n", gen.n_batch * 10))
    for i in range(total):
        generate_source(config, "vendor", i, dataset_dir / f"vendor{i}.nq")
        generate_source(config, "ratingsite", i, dataset_dir / f"ratingsite{i}.nq")


def _persist_source_rdf(
    config: BenchmarkConfig,
    section: str,
    source_name: str,
    graph: str,
    output_file: Path,
) -> None:
    try:
        from .artifacts import ArtifactStore, default_artifact_db

        db_path = default_artifact_db(config)
        store = ArtifactStore(db_path)
        config_id = store.persist_config(config, bench_dir=db_path.parent, artifact_db=db_path)
        for batch_key, members in config.generation.virtuoso.federation_members.items():
            if source_name not in members:
                continue
            batch_id = int(batch_key.replace("batch", ""))
            store.persist_rdf_file(
                config_id=config_id,
                batch_id=batch_id,
                source_name=source_name,
                source_type=section,
                graph=graph,
                file_path=output_file,
            )
    except Exception:
        pass
