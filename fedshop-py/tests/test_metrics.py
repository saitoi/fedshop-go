"""Tests for metrics.py — provenance CSV aggregation."""

import numpy as np
import pandas as pd
import pytest


def _write_provenance(path, data: dict):
    """Write a provenance.csv at path from a dict of {tp_name: [source, ...]}."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(data)
    df.to_csv(path, index=False)


def _write_results(path, n_rows: int = 3):
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"col": range(n_rows)}).to_csv(path, index=False)


def test_compute_metrics_empty_provenance_returns_nan_row(config_small, tmp_path):
    """Empty provenance.csv should produce a row with NaN metrics."""
    from fedshop.metrics import compute_metrics

    prov_path = tmp_path / "evaluation" / "fedx" / "q01" / "instance_0" / "batch_0" / "attempt_0" / "provenance.csv"
    prov_path.parent.mkdir(parents=True, exist_ok=True)
    prov_path.write_text("")  # empty

    outfile = tmp_path / "metrics.csv"
    df = compute_metrics(config_small, [str(prov_path)], outfile)

    assert outfile.exists()
    assert len(df) == 1
    assert pd.isna(df.iloc[0]["nb_distinct_sources"])
    assert pd.isna(df.iloc[0]["tpwss"])


def test_compute_metrics_tpwss_sums_distinct_sources_per_tp(config_small, tmp_path):
    """tpwss = sum of nunique per column in provenance.csv."""
    from fedshop.metrics import compute_metrics

    prov_path = tmp_path / "evaluation" / "fedx" / "q01" / "instance_0" / "batch_0" / "attempt_0" / "provenance.csv"
    _write_provenance(prov_path, {
        "tp0": ["a", "b", "a"],
        "tp1": ["c", "c", "d"],
    })
    _write_results(prov_path.parent / "results.csv", 3)

    outfile = tmp_path / "metrics.csv"
    df = compute_metrics(config_small, [str(prov_path)], outfile)

    # tp0 has 2 unique sources, tp1 has 2 unique sources → tpwss = 4
    assert df.iloc[0]["tpwss"] == 4.0


def test_compute_metrics_distinct_sources_counts_all_unique(config_small, tmp_path):
    """nb_distinct_sources counts unique values across all cells."""
    from fedshop.metrics import compute_metrics

    prov_path = tmp_path / "evaluation" / "fedx" / "q01" / "instance_0" / "batch_0" / "attempt_0" / "provenance.csv"
    _write_provenance(prov_path, {
        "tp0": ["source_a", "source_b"],
        "tp1": ["source_a", "source_c"],
    })
    _write_results(prov_path.parent / "results.csv", 2)

    outfile = tmp_path / "metrics.csv"
    df = compute_metrics(config_small, [str(prov_path)], outfile)

    assert df.iloc[0]["nb_distinct_sources"] == 3  # a, b, c


def test_compute_metrics_relevant_sources_selectivity_divides_by_total(config_small, tmp_path):
    """relevant_sources_selectivity = nb_distinct_sources / total_sources_for_batch."""
    from fedshop.metrics import compute_metrics

    prov_path = tmp_path / "evaluation" / "fedx" / "q01" / "instance_0" / "batch_0" / "attempt_0" / "provenance.csv"
    # batch 0 has 20 federation members (10 vendors + 10 ratingsites)
    _write_provenance(prov_path, {"tp0": ["a", "b", "c", "d", "e"]})
    _write_results(prov_path.parent / "results.csv", 5)

    outfile = tmp_path / "metrics.csv"
    df = compute_metrics(config_small, [str(prov_path)], outfile)

    expected = 5 / 20
    assert abs(df.iloc[0]["relevant_sources_selectivity"] - expected) < 1e-6


def test_compute_metrics_evaluation_mode_skips_rwss(config_small, tmp_path):
    """In evaluation mode (engine in config + attempt set), rwss columns should be None."""
    from fedshop.metrics import compute_metrics

    prov_path = tmp_path / "evaluation" / "fedx" / "q01" / "instance_0" / "batch_0" / "attempt_0" / "provenance.csv"
    _write_provenance(prov_path, {"tp0": ["a", "b"]})
    _write_results(prov_path.parent / "results.csv", 2)

    outfile = tmp_path / "metrics.csv"
    df = compute_metrics(config_small, [str(prov_path)], outfile)

    # fedx is in evaluation engines, so rwss should be null
    assert df.iloc[0]["avg_rwss"] is None or pd.isna(df.iloc[0]["avg_rwss"])


def test_compute_metrics_nb_results_from_results_csv(config_small, tmp_path):
    """nb_results should count rows in the sibling results.csv."""
    from fedshop.metrics import compute_metrics

    prov_path = tmp_path / "evaluation" / "fedx" / "q01" / "instance_0" / "batch_0" / "attempt_0" / "provenance.csv"
    _write_provenance(prov_path, {"tp0": ["a", "b", "c"]})
    _write_results(prov_path.parent / "results.csv", 7)

    outfile = tmp_path / "metrics.csv"
    df = compute_metrics(config_small, [str(prov_path)], outfile)

    assert df.iloc[0]["nb_results"] == 7
