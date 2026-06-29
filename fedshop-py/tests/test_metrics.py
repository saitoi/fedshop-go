"""Tests for metrics.py — provenance CSV aggregation."""

import numpy as np
import pandas as pd


# ─── Helpers for compute_full_metrics tests ────────────────────────────────

def _make_full_bench(tmp_path, engine, query, instance, batch, attempt,
                     exec_time="1.5", nb_engine_rows=None, nb_ref_rows=None,
                     prov_data=None):
    """Create a minimal bench_dir structure for compute_full_metrics."""
    base = (tmp_path / "evaluation" / engine / query
            / f"instance_{instance}" / f"batch_{batch}" / f"attempt_{attempt}")
    base.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{
        "engine": engine, "query": query, "instance": instance, "batch": batch,
        "attempt": attempt, "exec_time": exec_time,
        "source_selection_time": "0.1", "planning_time": "0.05",
        "ask": "5", "http_req": "10", "data_transfer": "1024",
    }]).to_csv(base / "stats.csv", index=False)

    if nb_engine_rows is not None:
        pd.DataFrame({"col": range(nb_engine_rows)}).to_csv(base / "results.csv", index=False)
    else:
        (base / "results.csv").write_text("")

    if prov_data is not None:
        pd.DataFrame(prov_data).to_csv(base / "provenance.csv", index=False)
    else:
        (base / "provenance.csv").write_text("")

    ref_dir = tmp_path / "generation" / query / f"instance_{instance}"
    ref_dir.mkdir(parents=True, exist_ok=True)
    if nb_ref_rows is not None:
        pd.DataFrame({"col": range(nb_ref_rows)}).to_csv(
            ref_dir / f"results-batch{batch}.csv", index=False)
    return tmp_path


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


def test_compute_metrics_reports_runtime_failure_status(config_small, tmp_path):
    from fedshop.metrics import compute_metrics

    prov_path = tmp_path / "evaluation" / "fedshop-go" / "q01" / "instance_0" / "batch_0" / "attempt_0" / "provenance.csv"
    prov_path.parent.mkdir(parents=True)
    prov_path.write_text("")
    pd.DataFrame([{"exec_time": "error_runtime"}]).to_csv(
        prov_path.parent / "stats.csv", index=False
    )

    df = compute_metrics(config_small, [prov_path], tmp_path / "metrics.csv")

    assert df.iloc[0]["status"] == "error_runtime"
    assert pd.isna(df.iloc[0]["nb_results"])


def test_compute_metrics_ignores_stale_artifacts_for_failed_attempt(config_small, tmp_path):
    """Failure status is authoritative even if an older run left non-empty CSVs."""
    from fedshop.metrics import compute_metrics

    prov_path = tmp_path / "evaluation" / "fedshop-go" / "q11" / "instance_0" / "batch_0" / "attempt_0" / "provenance.csv"
    _write_provenance(prov_path, {"tp0": ["stale-source"]})
    _write_results(prov_path.parent / "results.csv", 4000)
    pd.DataFrame([{"exec_time": "error_runtime"}]).to_csv(
        prov_path.parent / "stats.csv", index=False
    )

    df = compute_metrics(config_small, [prov_path], tmp_path / "metrics.csv")

    assert df.iloc[0]["status"] == "error_runtime"
    assert pd.isna(df.iloc[0]["nb_results"])
    assert pd.isna(df.iloc[0]["nb_distinct_sources"])
    assert pd.isna(df.iloc[0]["tpwss"])


def test_compute_metrics_keeps_valid_zero_results(config_small, tmp_path):
    from fedshop.metrics import compute_metrics

    prov_path = tmp_path / "evaluation" / "fedshop-go" / "q02" / "instance_0" / "batch_0" / "attempt_0" / "provenance.csv"
    _write_provenance(prov_path, {"tp0": ["source_a"]})
    pd.DataFrame(columns=["result"]).to_csv(prov_path.parent / "results.csv", index=False)
    pd.DataFrame([{"exec_time": 0.25}]).to_csv(prov_path.parent / "stats.csv", index=False)

    df = compute_metrics(config_small, [prov_path], tmp_path / "metrics.csv")

    assert df.iloc[0]["status"] == "ok"
    assert df.iloc[0]["nb_results"] == 0


# ─── compute_full_metrics tests ────────────────────────────────────────────


def test_full_metrics_float_exec_status_ok(config_small, tmp_path):
    """Float exec_time → status=ok, timing columns are floats."""
    from fedshop.metrics import compute_full_metrics
    _make_full_bench(tmp_path, "fedx", "q01", 0, 0, 0, exec_time="2.5")
    df = compute_full_metrics(config_small, tmp_path, tmp_path / "out.csv")
    assert len(df) == 1
    row = df.iloc[0]
    assert row["status"] == "ok"
    assert row["exec_time"] == 2.5
    assert row["source_selection_time"] == 0.1
    assert row["ask"] == 5.0


def test_full_metrics_timeout_flagged(config_small, tmp_path):
    """exec_time='timeout' → is_timeout=True, exec_time=NaN."""
    from fedshop.metrics import compute_full_metrics
    import math
    _make_full_bench(tmp_path, "pyfedx", "q02", 0, 0, 0, exec_time="timeout")
    df = compute_full_metrics(config_small, tmp_path, tmp_path / "out.csv")
    row = df.iloc[0]
    assert row["is_timeout"] == True  # noqa: E712 — numpy bool
    assert row["is_error"] == False
    assert math.isnan(row["exec_time"])


def test_full_metrics_error_flagged(config_small, tmp_path):
    """exec_time='error_runtime' → is_error=True."""
    from fedshop.metrics import compute_full_metrics
    _make_full_bench(tmp_path, "rsa", "q06", 1, 1, 0, exec_time="error_runtime")
    df = compute_full_metrics(config_small, tmp_path, tmp_path / "out.csv")
    row = df.iloc[0]
    assert row["is_error"] == True  # noqa: E712
    assert row["is_timeout"] == False


def test_full_metrics_mismatch_detected(config_small, tmp_path):
    """Engine returns 3 rows, reference has 5 → mismatch=True."""
    from fedshop.metrics import compute_full_metrics
    _make_full_bench(tmp_path, "fedx", "q06", 0, 0, 0, nb_engine_rows=3, nb_ref_rows=5)
    df = compute_full_metrics(config_small, tmp_path, tmp_path / "out.csv")
    assert df.iloc[0]["mismatch"] == True  # noqa: E712


def test_full_metrics_match_both_empty(config_small, tmp_path):
    """Both results empty → mismatch=False (correct answer is empty)."""
    from fedshop.metrics import compute_full_metrics
    bench = _make_full_bench(tmp_path, "fedx", "q01", 0, 0, 0, nb_engine_rows=0, nb_ref_rows=0)
    # Write empty ref file (0 rows, just header)
    ref = bench / "generation" / "q01" / "instance_0" / "results-batch0.csv"
    pd.DataFrame({"col": []}).to_csv(ref, index=False)
    results = bench / "evaluation" / "fedx" / "q01" / "instance_0" / "batch_0" / "attempt_0" / "results.csv"
    pd.DataFrame({"col": []}).to_csv(results, index=False)
    df = compute_full_metrics(config_small, tmp_path, tmp_path / "out.csv")
    assert df.iloc[0]["mismatch"] == False  # noqa: E712


def test_mismatch_column_missing_returns_true(tmp_path):
    """Engine results missing a reference column → mismatch=True (not None)."""
    from fedshop.metrics import _mismatch
    ref = tmp_path / "ref.csv"
    eng = tmp_path / "eng.csv"
    pd.DataFrame({"property": ["a"], "hasValue": ["x"], "isValueOf": ["1"]}).to_csv(ref, index=False)
    pd.DataFrame({"property": ["a"], "hasValue": ["x"]}).to_csv(eng, index=False)
    assert _mismatch(eng, ref) is True


def test_mismatch_float_precision_matches(tmp_path):
    """Numerically equal floats with different textual precision → mismatch=False."""
    from fedshop.metrics import _mismatch
    ref = tmp_path / "ref.csv"
    eng = tmp_path / "eng.csv"
    pd.DataFrame({"price": ["7289.2399999999997817"]}).to_csv(ref, index=False)
    pd.DataFrame({"price": ["7289.24"]}).to_csv(eng, index=False)
    assert _mismatch(eng, ref) is False


def test_full_metrics_no_provenance_has_timing(config_small, tmp_path):
    """Empty provenance → tpwss=NaN but timing/network metrics present."""
    from fedshop.metrics import compute_full_metrics
    import math
    _make_full_bench(tmp_path, "rsa", "q06", 0, 0, 0, exec_time="5.0")
    df = compute_full_metrics(config_small, tmp_path, tmp_path / "out.csv")
    row = df.iloc[0]
    assert row["exec_time"] == 5.0
    assert row["http_req"] == 10.0
    assert math.isnan(row["tpwss"])
    assert math.isnan(row["nb_distinct_sources"])
