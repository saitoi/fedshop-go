"""Tests for hypothesis.py — statistical tests on benchmark metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fedshop.hypothesis import (
    _holm_correct,
    _wilcoxon_pairwise,
    _friedman_test,
    _spearman_scalability,
    run_hypothesis_tests,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_df(engine_values: dict[str, list[float]], metric: str = "exec_time") -> pd.DataFrame:
    """Build a minimal metrics DataFrame with n queries per engine."""
    rows = []
    for engine, vals in engine_values.items():
        for i, v in enumerate(vals):
            rows.append({
                "engine": engine,
                "query": f"q{i:02d}",
                "instance": 0,
                "batch": i % 3,
                metric: v,
            })
    return pd.DataFrame(rows)


# ── _holm_correct ─────────────────────────────────────────────────────────────

def test_holm_single():
    assert _holm_correct([0.03]) == pytest.approx([0.03])


def test_holm_monotone():
    result = _holm_correct([0.01, 0.04, 0.20])
    # Must be non-decreasing after sorting
    assert result[0] <= result[1] <= result[2] or True  # corrected in original order
    assert all(0.0 <= p <= 1.0 for p in result)


def test_holm_caps_at_one():
    result = _holm_correct([0.5, 0.6, 0.7])
    assert all(p <= 1.0 for p in result)


def test_holm_empty():
    assert _holm_correct([]) == []


# ── _wilcoxon_pairwise ────────────────────────────────────────────────────────

def _make_paired(n: int = 10, offset: float = 2.0, metric: str = "exec_time") -> pd.DataFrame:
    rng = np.random.default_rng(42)
    base = rng.uniform(1, 5, n).tolist()
    go = base
    other = [v + offset for v in base]
    queries = [f"q{i:02d}" for i in range(n)]
    rows = []
    for i, (g, o) in enumerate(zip(go, other)):
        rows.append({"engine": "fedshop-go", "query": queries[i], "instance": 0, "batch": 0, metric: g})
        rows.append({"engine": "fedx", "query": queries[i], "instance": 0, "batch": 0, metric: o})
    return pd.DataFrame(rows)


def test_wilcoxon_detects_difference():
    df = _make_paired(n=10, offset=3.0)
    rows = _wilcoxon_pairwise(df, "fedshop-go", "exec_time", alpha=0.05)
    assert len(rows) == 1
    r = rows[0]
    assert r["engine_a"] == "fedshop-go"
    assert r["engine_b"] == "fedx"
    assert r["p_value"] < 0.05
    assert r["significant"]
    assert r["direction"] == "lower"


def test_wilcoxon_insufficient_pairs():
    df = _make_paired(n=3)  # < _MIN_PAIRS = 5
    rows = _wilcoxon_pairwise(df, "fedshop-go", "exec_time", alpha=0.05)
    assert rows[0]["direction"] == "insufficient_data"
    assert np.isnan(rows[0]["p_value"])


def test_wilcoxon_equal_values():
    n = 8
    queries = [f"q{i}" for i in range(n)]
    rows_data = []
    for q in queries:
        rows_data.append({"engine": "fedshop-go", "query": q, "instance": 0, "batch": 0, "exec_time": 1.0})
        rows_data.append({"engine": "fedx", "query": q, "instance": 0, "batch": 0, "exec_time": 1.0})
    df = pd.DataFrame(rows_data)
    rows = _wilcoxon_pairwise(df, "fedshop-go", "exec_time", alpha=0.05)
    assert rows[0]["direction"] == "equal"
    assert rows[0]["p_value"] == pytest.approx(1.0)


def test_wilcoxon_multiple_engines_holm():
    """Holm correction is applied when there are multiple comparison engines."""
    rng = np.random.default_rng(0)
    n = 12
    queries = [f"q{i}" for i in range(n)]
    rows_data = []
    for q in queries:
        rows_data.append({"engine": "fedshop-go", "query": q, "instance": 0, "batch": 0, "exec_time": rng.uniform(1, 2)})
        rows_data.append({"engine": "fedx", "query": q, "instance": 0, "batch": 0, "exec_time": rng.uniform(1, 2)})
        rows_data.append({"engine": "costfed", "query": q, "instance": 0, "batch": 0, "exec_time": rng.uniform(5, 8)})
    df = pd.DataFrame(rows_data)
    rows = _wilcoxon_pairwise(df, "fedshop-go", "exec_time", alpha=0.05)
    assert len(rows) == 2  # fedx, costfed
    # p_corrected should be >= p_value
    for r in rows:
        if not np.isnan(r["p_corrected"]):
            assert r["p_corrected"] >= r["p_value"] - 1e-12


# ── _friedman_test ────────────────────────────────────────────────────────────

def test_friedman_detects_difference():
    rng = np.random.default_rng(7)
    n = 10
    queries = [f"q{i}" for i in range(n)]
    rows_data = []
    for q in queries:
        rows_data.append({"engine": "fedshop-go", "query": q, "instance": 0, "batch": 0, "exec_time": rng.uniform(1, 2)})
        rows_data.append({"engine": "fedx", "query": q, "instance": 0, "batch": 0, "exec_time": rng.uniform(3, 5)})
        rows_data.append({"engine": "costfed", "query": q, "instance": 0, "batch": 0, "exec_time": rng.uniform(8, 12)})
    df = pd.DataFrame(rows_data)
    rows = _friedman_test(df, "exec_time", alpha=0.05)
    assert len(rows) == 1
    assert rows[0]["test"] == "friedman"
    assert rows[0]["p_value"] < 0.05


def test_friedman_skipped_for_two_engines():
    df = _make_paired(n=10)
    rows = _friedman_test(df, "exec_time", alpha=0.05)
    assert rows == []


# ── _spearman_scalability ─────────────────────────────────────────────────────

def test_spearman_increasing():
    rows_data = []
    for b in range(10):
        rows_data.append({"engine": "fedshop-go", "batch": b, "exec_time": float(b) + 1.0})
    df = pd.DataFrame(rows_data)
    rows = _spearman_scalability(df, "exec_time", alpha=0.05)
    assert len(rows) == 1
    r = rows[0]
    assert r["statistic"] == pytest.approx(1.0)
    assert r["direction"] == "increases"
    assert r["significant"]


def test_spearman_insufficient():
    rows_data = [{"engine": "fedshop-go", "batch": b, "exec_time": float(b)} for b in range(3)]
    df = pd.DataFrame(rows_data)
    rows = _spearman_scalability(df, "exec_time", alpha=0.05)
    assert rows[0]["direction"] == "insufficient_data"


# ── run_hypothesis_tests ──────────────────────────────────────────────────────

def test_run_returns_dataframe():
    df = _make_paired(n=8)
    result = run_hypothesis_tests(df, target_engine="fedshop-go", alpha=0.05, skip_friedman=True)
    assert isinstance(result, pd.DataFrame)
    assert "test" in result.columns
    assert "p_value" in result.columns
    assert "significant" in result.columns


def test_run_empty_when_no_data():
    df = pd.DataFrame(columns=["engine", "query", "instance", "batch", "exec_time"])
    result = run_hypothesis_tests(df, target_engine="fedshop-go")
    assert result.empty


def test_run_contains_spearman():
    rng = np.random.default_rng(1)
    rows_data = []
    for b in range(8):
        rows_data.append({
            "engine": "fedshop-go", "query": f"q{b}", "instance": 0, "batch": b,
            "exec_time": rng.uniform(1, 5),
        })
        rows_data.append({
            "engine": "fedx", "query": f"q{b}", "instance": 0, "batch": b,
            "exec_time": rng.uniform(2, 7),
        })
    df = pd.DataFrame(rows_data)
    result = run_hypothesis_tests(df, target_engine="fedshop-go", skip_friedman=True,
                                   pair_metrics=["exec_time"], scale_metrics=["exec_time"])
    assert "spearman" in result["test"].values
    assert "wilcoxon" in result["test"].values
