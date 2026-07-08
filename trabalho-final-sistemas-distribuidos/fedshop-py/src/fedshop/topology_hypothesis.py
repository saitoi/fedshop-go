"""Hypothesis tests over the merged per-topology metrics (HT1–HT5).

Input: the merged CSV produced by `fedshop topology merge` (one row per
engine/query/instance/batch/attempt/topology). All tests are non-parametric,
mirroring hypothesis.py: Friedman omnibus, paired Wilcoxon with Holm
correction, and Spearman rank correlation. hypothesis.py itself is untouched.

HT1  Topology affects exec_time (Friedman T1/T2/T3 + post-hoc Wilcoxon pairs).
HT2  Chattier engines suffer more: Spearman between baseline request count and
     the slowdown observed at a distributed topology.
HT3  Source selection is the phase most affected by latency: paired Wilcoxon
     between per-block phase slowdown ratios (source selection vs join).
HT4  Scale×topology interaction: Spearman exec_time vs batch per topology.
HT5  Splitting endpoints across two machines (T3) vs one (T2): paired Wilcoxon.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import friedmanchisquare, spearmanr, wilcoxon

from .hypothesis import _holm_correct

_MIN_PAIRS = 5

_BLOCK_KEYS = ["engine", "query", "instance", "batch"]

_RESULT_COLS = [
    "hypothesis", "test", "metric", "group_a", "group_b", "n_pairs",
    "statistic", "p_value", "p_corrected", "significant",
    "median_a", "median_b", "direction",
]


def _row(hypothesis: str, test: str, metric: str, a: str, b: str, n: int, **kw) -> dict:
    base = {
        "hypothesis": hypothesis,
        "test": test,
        "metric": metric,
        "group_a": a,
        "group_b": b,
        "n_pairs": n,
        "statistic": np.nan,
        "p_value": np.nan,
        "p_corrected": np.nan,
        "significant": False,
        "median_a": np.nan,
        "median_b": np.nan,
        "direction": "",
    }
    base.update(kw)
    return base


def _block_median(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    """Median of `metric` over attempts per (block, topology), ok rows only."""
    ok = df[(df["status"] == "ok") & df[metric].notna()]
    return (
        ok.groupby(_BLOCK_KEYS + ["topology"])[metric]
        .median()
        .reset_index()
    )


def _pivot(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    """Blocks as rows, topologies as columns, block-median metric as values."""
    medians = _block_median(df, metric)
    return medians.pivot_table(index=_BLOCK_KEYS, columns="topology", values=metric)


def _paired_wilcoxon(
    hypothesis: str,
    metric: str,
    a: pd.Series,
    b: pd.Series,
    label_a: str,
    label_b: str,
    alpha: float,
) -> dict:
    paired = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    n = len(paired)
    if n < _MIN_PAIRS:
        return _row(hypothesis, "wilcoxon", metric, label_a, label_b, n, direction="insufficient_data")
    med_a, med_b = float(paired["a"].median()), float(paired["b"].median())
    direction = "lower" if med_a < med_b else ("higher" if med_a > med_b else "equal")
    diffs = paired["a"].values - paired["b"].values
    if np.all(diffs == 0):
        return _row(
            hypothesis, "wilcoxon", metric, label_a, label_b, n,
            p_value=1.0, p_corrected=1.0, median_a=med_a, median_b=med_b, direction="equal",
        )
    try:
        stat, p = wilcoxon(paired["a"].values, paired["b"].values)
    except Exception:
        stat, p = np.nan, np.nan
    return _row(
        hypothesis, "wilcoxon", metric, label_a, label_b, n,
        statistic=stat, p_value=p, median_a=med_a, median_b=med_b, direction=direction,
    )


def _holm_apply(rows: list[dict], alpha: float) -> None:
    """Holm correction in place over the rows that produced a raw p-value."""
    idx = [i for i, r in enumerate(rows) if not np.isnan(r.get("p_value", np.nan)) and np.isnan(r.get("p_corrected", np.nan))]
    if not idx:
        return
    corrected = _holm_correct([rows[i]["p_value"] for i in idx])
    for j, i in enumerate(idx):
        rows[i]["p_corrected"] = corrected[j]
        rows[i]["significant"] = corrected[j] < alpha


# ─── HT1: topology affects exec_time ─────────────────────────────────────────

def ht1_topology_effect(df: pd.DataFrame, alpha: float, metric: str = "exec_time") -> list[dict]:
    wide = _pivot(df, metric)
    topologies = sorted(wide.columns)
    rows: list[dict] = []

    if len(topologies) >= 3:
        complete = wide.dropna()
        n = len(complete)
        if n < _MIN_PAIRS:
            rows.append(_row("HT1", "friedman", metric, "all", "all", n, direction="insufficient_data"))
        else:
            try:
                stat, p = friedmanchisquare(*[complete[t].values for t in topologies])
            except Exception:
                stat, p = np.nan, np.nan
            rows.append(_row(
                "HT1", "friedman", metric, "all", "all", n,
                statistic=stat, p_value=p, p_corrected=p,
                significant=bool(p < alpha) if not np.isnan(p) else False,
                direction=f"topologies={','.join(topologies)}",
            ))

    post_hoc: list[dict] = []
    for i, ta in enumerate(topologies):
        for tb in topologies[i + 1:]:
            post_hoc.append(_paired_wilcoxon("HT1", metric, wide[ta], wide[tb], ta, tb, alpha))
    _holm_apply(post_hoc, alpha)
    return rows + post_hoc


# ─── HT2: chattier engines suffer more ───────────────────────────────────────

def ht2_request_sensitivity(
    df: pd.DataFrame,
    alpha: float,
    *,
    baseline: str = "topo1",
    distributed: str = "topo3",
    request_metric: str = "http_req",
) -> list[dict]:
    exec_wide = _pivot(df, "exec_time")
    if baseline not in exec_wide.columns or distributed not in exec_wide.columns:
        return [_row("HT2", "spearman", request_metric, baseline, distributed, 0, direction="missing_topology")]
    slowdown = (exec_wide[distributed] / exec_wide[baseline]).rename("slowdown")
    req_wide = _pivot(df, request_metric)
    if baseline not in req_wide.columns:
        return [_row("HT2", "spearman", request_metric, baseline, distributed, 0, direction="missing_topology")]
    requests = req_wide[baseline].rename("requests")
    joined = pd.concat([requests, slowdown], axis=1).dropna().reset_index()

    rows: list[dict] = []
    scopes = [("all", joined)] + [(e, g) for e, g in joined.groupby("engine")]
    for scope, sub in scopes:
        n = len(sub)
        if n < _MIN_PAIRS:
            rows.append(_row("HT2", "spearman", request_metric, scope, f"slowdown_{distributed}", n, direction="insufficient_data"))
            continue
        try:
            rho, p = spearmanr(sub["requests"].values, sub["slowdown"].values)
        except Exception:
            rho, p = np.nan, np.nan
        direction = "increases" if (not np.isnan(rho) and rho > 0) else ("decreases" if (not np.isnan(rho) and rho < 0) else "flat")
        rows.append(_row(
            "HT2", "spearman", request_metric, scope, f"slowdown_{distributed}", n,
            statistic=rho, p_value=p, p_corrected=p,
            significant=bool(p < alpha) if not np.isnan(p) else False,
            median_a=float(sub["requests"].median()), median_b=float(sub["slowdown"].median()),
            direction=direction,
        ))
    return rows


# ─── HT3: which phase suffers most from latency ──────────────────────────────

def ht3_phase_impact(
    df: pd.DataFrame,
    alpha: float,
    *,
    baseline: str = "topo1",
    distributed: str = "topo3",
    phases: tuple[str, str] = ("source_selection_time", "join_time"),
) -> list[dict]:
    ratios: dict[str, pd.Series] = {}
    for phase in phases:
        wide = _pivot(df, phase)
        if baseline not in wide.columns or distributed not in wide.columns:
            return [_row("HT3", "wilcoxon", "+".join(phases), baseline, distributed, 0, direction="missing_topology")]
        base = wide[baseline].replace(0, np.nan)
        ratios[phase] = (wide[distributed] / base).rename(phase)
    row = _paired_wilcoxon(
        "HT3", f"{phases[0]}_ratio_vs_{phases[1]}_ratio",
        ratios[phases[0]], ratios[phases[1]],
        f"{phases[0]}_ratio", f"{phases[1]}_ratio", alpha,
    )
    row["p_corrected"] = row["p_value"]
    if not np.isnan(row.get("p_value", np.nan)):
        row["significant"] = row["p_value"] < alpha
    return [row]


# ─── HT4: scalability × topology ─────────────────────────────────────────────

def ht4_scale_topology(df: pd.DataFrame, alpha: float, metric: str = "exec_time") -> list[dict]:
    medians = _block_median(df, metric)
    rows: list[dict] = []
    for (engine, topology), sub in medians.groupby(["engine", "topology"]):
        n = len(sub)
        if n < _MIN_PAIRS:
            rows.append(_row("HT4", "spearman", metric, engine, topology, n, direction="insufficient_data"))
            continue
        try:
            rho, p = spearmanr(sub["batch"].values, sub[metric].values)
        except Exception:
            rho, p = np.nan, np.nan
        direction = "increases" if (not np.isnan(rho) and rho > 0) else ("decreases" if (not np.isnan(rho) and rho < 0) else "flat")
        rows.append(_row(
            "HT4", "spearman", metric, engine, topology, n,
            statistic=rho, p_value=p, p_corrected=p,
            significant=bool(p < alpha) if not np.isnan(p) else False,
            median_a=float(sub[metric].median()), direction=direction,
        ))
    return rows


# ─── HT5: T2 vs T3 ───────────────────────────────────────────────────────────

def ht5_split_endpoints(df: pd.DataFrame, alpha: float, metric: str = "exec_time") -> list[dict]:
    wide = _pivot(df, metric)
    if "topo2" not in wide.columns or "topo3" not in wide.columns:
        return [_row("HT5", "wilcoxon", metric, "topo2", "topo3", 0, direction="missing_topology")]
    rows: list[dict] = [
        _paired_wilcoxon("HT5", metric, wide["topo2"], wide["topo3"], "topo2", "topo3", alpha)
    ]
    for engine in sorted({e for e, *_ in wide.index}):
        sub = wide.xs(engine, level="engine")
        rows.append(_paired_wilcoxon(
            "HT5", metric, sub["topo2"], sub["topo3"], f"topo2[{engine}]", f"topo3[{engine}]", alpha,
        ))
    _holm_apply(rows, alpha)
    return rows


# ─── Entry point ─────────────────────────────────────────────────────────────

def run_topology_hypothesis_tests(df: pd.DataFrame, alpha: float = 0.05) -> pd.DataFrame:
    """Run HT1–HT5 over a merged per-topology metrics DataFrame."""
    required = {"topology", "status", "exec_time"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"merged metrics CSV is missing columns: {sorted(missing)}")

    records: list[dict] = []
    records.extend(ht1_topology_effect(df, alpha))
    records.extend(ht2_request_sensitivity(df, alpha))
    records.extend(ht3_phase_impact(df, alpha))
    records.extend(ht4_scale_topology(df, alpha))
    records.extend(ht5_split_endpoints(df, alpha))

    result = pd.DataFrame.from_records(records)
    return result[[c for c in _RESULT_COLS if c in result.columns]].reset_index(drop=True)
