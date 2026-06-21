from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .config import BenchmarkConfig


def generate_source(
    config: BenchmarkConfig,
    section: str,
    source_id: int,
    output_file: Path,
    product_dir: Path | None = None,
) -> Path:
    """Fill WatDiv template placeholders for one federation member and run WatDiv.

    Returns path to the generated .nq file (written by WatDiv to stdout → output_file).
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
    cmd = f"{gen.generator.exec} -d {model_file} {scale_factor}"

    output_file.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, shell=True, stdout=output_file.open("wb"), check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"WatDiv failed for {source_name} (exit {proc.returncode})")

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
    exec_abs = Path(gen.generator.exec).resolve()
    cmd = f"{exec_abs} -d {model_file.resolve()} {scale_factor}"

    proc = subprocess.run(cmd, shell=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"WatDiv failed for products (exit {proc.returncode})")

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

    total = gen.n_batch * 10
    for i in range(total):
        generate_source(config, "vendor", i, dataset_dir / f"vendor{i}.nq")
        generate_source(config, "ratingsite", i, dataset_dir / f"ratingsite{i}.nq")
