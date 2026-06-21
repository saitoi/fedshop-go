from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from .config import BenchmarkConfig


def _vendor_ratingsite_edges(config: BenchmarkConfig) -> tuple[np.ndarray, np.ndarray]:
    """Compute cumulative member counts per batch (matching the reference histogram logic)."""
    n_batch = config.generation.n_batch
    vendor_n = config.generation.schema["vendor"].params.get("vendor_n", n_batch * 10)
    ratingsite_n = config.generation.schema["ratingsite"].params.get("ratingsite_n", n_batch * 10)

    vendor_data = np.arange(int(vendor_n))
    ratingsite_data = np.arange(int(ratingsite_n))

    _, vendor_edges = np.histogram(vendor_data, n_batch)
    _, ratingsite_edges = np.histogram(ratingsite_data, n_batch)

    vendor_edges = vendor_edges[1:].astype(int) + 1
    ratingsite_edges = ratingsite_edges[1:].astype(int) + 1
    return vendor_edges, ratingsite_edges


def _parse_path(provenance_file: str) -> dict | None:
    m = re.search(
        r".*/(\w+)/(q\w+)/instance_(\d+)/batch_(\d+)/((attempt_(\d+)|test)/)?provenance.csv",
        provenance_file,
    )
    if not m:
        return None
    return {
        "engine": m.group(1),
        "query": m.group(2),
        "instance": int(m.group(3)),
        "batch": int(m.group(4)),
        "attempt": m.group(7),
    }


def _get_rwss(df: pd.DataFrame, agg: str, is_evaluation_mode: bool):
    if is_evaluation_mode:
        return None
    result = df.apply(pd.Series.nunique, axis=1).describe()
    return result[agg]


def _get_tpwss(df: pd.DataFrame) -> float:
    return float(df.apply(pd.Series.nunique).sum())


def _get_distinct_sources(df: pd.DataFrame) -> int:
    return int(pd.Series(df.values.flatten()).nunique())


def compute_metrics(
    config: BenchmarkConfig,
    provenance_files: list[str | Path],
    output_path: str | Path,
) -> pd.DataFrame:
    """Aggregate provenance CSVs into a metrics DataFrame and write to output_path."""
    vendor_edges, ratingsite_edges = _vendor_ratingsite_edges(config)
    eval_engine_names = set(config.evaluation.engines.keys())

    records = []
    for pf in provenance_files:
        pf_str = str(pf)
        meta = _parse_path(pf_str)
        if meta is None:
            continue

        batch = meta["batch"]
        total_nb_sources = int(vendor_edges[batch]) + int(ratingsite_edges[batch])
        results_file = Path(pf_str).parent / "results.csv"

        is_evaluation_mode = (meta["engine"] in eval_engine_names) and (meta["attempt"] is not None)

        record: dict = {}
        if is_evaluation_mode:
            record["attempt"] = int(meta["attempt"]) if meta["attempt"] else None
            record["engine"] = meta["engine"]

        with open(pf_str) as ss_fs:
            content = ss_fs.read().strip()

        if not content:
            record.update({
                "query": meta["query"],
                "instance": meta["instance"],
                "batch": batch,
                "nb_results": np.nan,
                "nb_distinct_sources": np.nan,
                "relevant_sources_selectivity": np.nan,
                "tpwss": np.nan,
                "avg_rwss": np.nan,
                "min_rwss": np.nan,
                "max_rwss": np.nan,
            })
        else:
            ss_df = pd.read_csv(pf_str)
            nb_results = np.nan
            if results_file.exists():
                with open(results_file) as rfs:
                    if rfs.read().strip():
                        nb_results = len(pd.read_csv(str(results_file)))

            distinct = _get_distinct_sources(ss_df)
            record.update({
                "query": meta["query"],
                "instance": meta["instance"],
                "batch": batch,
                "nb_results": nb_results,
                "nb_distinct_sources": distinct,
                "relevant_sources_selectivity": distinct / total_nb_sources,
                "tpwss": _get_tpwss(ss_df),
                "avg_rwss": _get_rwss(ss_df, "mean", is_evaluation_mode),
                "min_rwss": _get_rwss(ss_df, "min", is_evaluation_mode),
                "max_rwss": _get_rwss(ss_df, "max", is_evaluation_mode),
            })

        records.append(record)

    metrics_df = pd.DataFrame.from_records(records)
    metrics_df.to_csv(str(output_path), index=False)
    return metrics_df
