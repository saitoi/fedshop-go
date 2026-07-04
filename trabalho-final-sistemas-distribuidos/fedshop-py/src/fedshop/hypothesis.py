"""Statistical hypothesis tests for FedShop benchmark metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import friedmanchisquare, spearmanr, wilcoxon

_PAIR_METRICS = [
    "exec_time",
    "source_selection_time",
    "planning_time",
    "f1",
    "precision",
    "recall",
    "tpwss",
    "avg_rwss",
    "redundant_requests",
    "false_positive_sources",
]

_SCALE_METRICS = ["exec_time", "tpwss", "avg_rwss"]

_MIN_PAIRS = 5


def _holm_correct(p_values: list[float]) -> list[float]:
    """Holm-Bonferroni correction, returns adjusted p-values in original order."""
    n = len(p_values)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: p_values[i])
    corrected = [0.0] * n
    running_max = 0.0
    for rank, idx in enumerate(order):
        adj = min(p_values[idx] * (n - rank), 1.0)
        running_max = max(running_max, adj)
        corrected[idx] = running_max
    return corrected


def _empty_row(test: str, metric: str, engine_a: str, engine_b: str, n: int, reason: str) -> dict:
    return {
        "test": test,
        "metric": metric,
        "engine_a": engine_a,
        "engine_b": engine_b,
        "n_pairs": n,
        "statistic": np.nan,
        "p_value": np.nan,
        "p_corrected": np.nan,
        "significant": False,
        "median_a": np.nan,
        "median_b": np.nan,
        "direction": reason,
    }


def _wilcoxon_pairwise(
    df: pd.DataFrame,
    target_engine: str,
    metric: str,
    alpha: float,
) -> list[dict]:
    """Wilcoxon signed-rank: target_engine vs every other engine, paired by (query, instance, batch)."""
    target = df[df["engine"] == target_engine]
    others = sorted(e for e in df["engine"].unique() if e != target_engine)
    rows: list[dict] = []

    for other in others:
        other_df = df[df["engine"] == other]
        merged = pd.merge(
            target[["query", "instance", "batch", metric]].rename(columns={metric: "a"}),
            other_df[["query", "instance", "batch", metric]].rename(columns={metric: "b"}),
            on=["query", "instance", "batch"],
        ).dropna(subset=["a", "b"])
        n = len(merged)

        if n < _MIN_PAIRS:
            rows.append(_empty_row("wilcoxon", metric, target_engine, other, n, "insufficient_data"))
            continue

        diffs = merged["a"].values - merged["b"].values
        med_a = float(np.median(merged["a"]))
        med_b = float(np.median(merged["b"]))
        direction = "lower" if med_a < med_b else ("higher" if med_a > med_b else "equal")

        if np.all(diffs == 0):
            rows.append({
                **_empty_row("wilcoxon", metric, target_engine, other, n, "equal"),
                "p_value": 1.0,
                "p_corrected": 1.0,
                "median_a": med_a,
                "median_b": med_b,
                "direction": "equal",
            })
            continue

        try:
            stat, p = wilcoxon(merged["a"].values, merged["b"].values)
        except Exception:
            stat, p = np.nan, np.nan

        rows.append({
            "test": "wilcoxon",
            "metric": metric,
            "engine_a": target_engine,
            "engine_b": other,
            "n_pairs": n,
            "statistic": stat,
            "p_value": p,
            "p_corrected": np.nan,
            "significant": False,
            "median_a": med_a,
            "median_b": med_b,
            "direction": direction,
        })

    # Holm correction across engines for this metric
    valid_idx = [i for i, r in enumerate(rows) if not np.isnan(r.get("p_value", np.nan)) and r["p_value"] != 1.0]
    if valid_idx:
        raw_p = [rows[i]["p_value"] for i in valid_idx]
        corrected = _holm_correct(raw_p)
        for j, i in enumerate(valid_idx):
            rows[i]["p_corrected"] = corrected[j]
            rows[i]["significant"] = corrected[j] < alpha

    return rows


def _friedman_test(
    df: pd.DataFrame,
    metric: str,
    alpha: float,
) -> list[dict]:
    """Friedman test across all engines, blocked by (query, instance, batch)."""
    engines = sorted(df["engine"].unique())
    if len(engines) < 3:
        return []

    groups: dict[str, pd.Series] = {}
    for eng in engines:
        sub = df[df["engine"] == eng][["query", "instance", "batch", metric]].dropna(subset=[metric])
        groups[eng] = sub.set_index(["query", "instance", "batch"])[metric]

    common_idx = groups[engines[0]].index
    for eng in engines[1:]:
        common_idx = common_idx.intersection(groups[eng].index)

    n = len(common_idx)
    if n < _MIN_PAIRS:
        return [_empty_row("friedman", metric, "all", "all", n, "insufficient_data")]

    samples = [groups[eng].loc[common_idx].values for eng in engines]
    try:
        stat, p = friedmanchisquare(*samples)
    except Exception:
        stat, p = np.nan, np.nan

    return [{
        "test": "friedman",
        "metric": metric,
        "engine_a": "all",
        "engine_b": "all",
        "n_pairs": n,
        "statistic": stat,
        "p_value": p,
        "p_corrected": p,
        "significant": bool(p < alpha) if not np.isnan(p) else False,
        "median_a": np.nan,
        "median_b": np.nan,
        "direction": f"engines={','.join(engines)}",
    }]


def _spearman_scalability(
    df: pd.DataFrame,
    metric: str,
    alpha: float,
) -> list[dict]:
    """Spearman ρ between batch_id and metric per engine (scalability test)."""
    rows: list[dict] = []
    for engine in sorted(df["engine"].unique()):
        sub = df[df["engine"] == engine][["batch", metric]].dropna(subset=[metric])
        n = len(sub)
        if n < _MIN_PAIRS:
            rows.append(_empty_row("spearman", metric, engine, "batch", n, "insufficient_data"))
            continue
        try:
            rho, p = spearmanr(sub["batch"].values, sub[metric].values)
        except Exception:
            rho, p = np.nan, np.nan
        direction = "increases" if (not np.isnan(rho) and rho > 0) else ("decreases" if (not np.isnan(rho) and rho < 0) else "flat")
        rows.append({
            "test": "spearman",
            "metric": metric,
            "engine_a": engine,
            "engine_b": "batch",
            "n_pairs": n,
            "statistic": rho,
            "p_value": p,
            "p_corrected": p,
            "significant": bool(p < alpha) if not np.isnan(p) else False,
            "median_a": float(np.median(sub[metric])),
            "median_b": np.nan,
            "direction": direction,
        })
    return rows


_RESULT_COLS = [
    "test", "metric", "engine_a", "engine_b", "n_pairs",
    "statistic", "p_value", "p_corrected", "significant",
    "median_a", "median_b", "direction",
]


def run_hypothesis_tests(
    df: pd.DataFrame,
    target_engine: str = "fedshop-go",
    alpha: float = 0.05,
    pair_metrics: list[str] | None = None,
    scale_metrics: list[str] | None = None,
    skip_friedman: bool = False,
) -> pd.DataFrame:
    """Run Wilcoxon, Friedman, and Spearman tests on benchmark metrics.

    Args:
        df: Full metrics DataFrame from compute_full_metrics.
        target_engine: Engine to use as the focal comparison point for Wilcoxon.
        alpha: Significance level (default 0.05).
        pair_metrics: Override which metrics to use for Wilcoxon/Friedman.
        scale_metrics: Override which metrics to use for Spearman scalability.
        skip_friedman: Skip Friedman test (useful when < 3 engines present).

    Returns:
        DataFrame with one row per (test, metric, engine_a, engine_b).
    """
    if pair_metrics is None:
        pair_metrics = [m for m in _PAIR_METRICS if m in df.columns]
    if scale_metrics is None:
        scale_metrics = [m for m in _SCALE_METRICS if m in df.columns]

    records: list[dict] = []

    for metric in pair_metrics:
        records.extend(_wilcoxon_pairwise(df, target_engine, metric, alpha))

    if not skip_friedman:
        for metric in pair_metrics:
            records.extend(_friedman_test(df, metric, alpha))

    for metric in scale_metrics:
        records.extend(_spearman_scalability(df, metric, alpha))

    if not records:
        return pd.DataFrame(columns=_RESULT_COLS)

    result_df = pd.DataFrame.from_records(records)
    result_df = result_df[[c for c in _RESULT_COLS if c in result_df.columns]]
    return result_df.sort_values(["test", "metric", "engine_a", "engine_b"]).reset_index(drop=True)
