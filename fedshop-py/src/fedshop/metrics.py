from __future__ import annotations

import json
import re
from collections import Counter
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
        r".*/([\w-]+)/(q\w+)/instance_(\d+)/batch_(\d+)/((attempt_(\d+)|test)/)?provenance.csv",
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


def _get_rwss(df: pd.DataFrame, agg: str) -> float:
    result = df.apply(pd.Series.nunique, axis=1).describe()
    return float(result[agg])


def _get_tpwss(df: pd.DataFrame) -> float:
    return float(df.apply(pd.Series.nunique).sum())


def _get_distinct_sources(df: pd.DataFrame) -> int:
    return int(pd.Series(df.values.flatten()).nunique())


def _parse_source_selection(ss_file: Path) -> list[set[str]]:
    """Return selected endpoints per TP (ordered), parsed from source_selection.txt."""
    if not ss_file.exists() or ss_file.stat().st_size == 0:
        return []
    try:
        df = pd.read_csv(ss_file)
        result = []
        for _, row in df.iterrows():
            raw = row.get("source_selection", "[]")
            try:
                endpoints = set(json.loads(raw))
            except (ValueError, TypeError):
                endpoints = set()
            result.append(endpoints)
        return result
    except Exception:
        return []


def _get_false_positive_sources(ss_file: Path, prov_df: pd.DataFrame) -> int:
    """Count endpoints selected but absent from every result row in provenance."""
    selected_per_tp = _parse_source_selection(ss_file)
    if not selected_per_tp:
        return 0
    all_selected = set().union(*selected_per_tp)
    flat = prov_df.values.flatten()
    contributing = {v for v in flat if isinstance(v, str) and v.strip()}
    return len(all_selected - contributing)


def _get_redundant_requests(ss_file: Path, prov_df: pd.DataFrame) -> int:
    """Count (TP-index, endpoint) pairs selected but absent from provenance result rows."""
    selected_per_tp = _parse_source_selection(ss_file)
    if not selected_per_tp:
        return 0
    selected_pairs: set[tuple[int, str]] = set()
    for tp_idx, endpoints in enumerate(selected_per_tp):
        for ep in endpoints:
            selected_pairs.add((tp_idx, ep))
    contributing_pairs: set[tuple[int, str]] = set()
    for tp_idx, col in enumerate(prov_df.columns):
        for v in prov_df[col]:
            if isinstance(v, str) and v.strip():
                contributing_pairs.add((tp_idx, v))
    return len(selected_pairs - contributing_pairs)


def _attempt_status(stats_file: Path) -> str:
    if not stats_file.exists() or stats_file.stat().st_size == 0:
        return "missing_stats"
    try:
        stats = pd.read_csv(stats_file)
    except Exception:
        return "missing_stats"
    if stats.empty or "exec_time" not in stats.columns:
        return "missing_stats"
    value = stats.iloc[0]["exec_time"]
    try:
        float(value)
        return "ok"
    except (TypeError, ValueError):
        return str(value)


def _parse_stats_path(stats_file: str) -> dict | None:
    m = re.search(
        r".*/([^/]+)/(q\w+)/instance_(\d+)/batch_(\d+)/attempt_(\d+)/stats\.csv$",
        stats_file,
    )
    if not m:
        return None
    return {
        "engine": m.group(1),
        "query": m.group(2),
        "instance": int(m.group(3)),
        "batch": int(m.group(4)),
        "attempt": int(m.group(5)),
    }


def _read_stats_row(stats_file: Path) -> dict:
    try:
        return pd.read_csv(stats_file).iloc[0].to_dict()
    except Exception:
        return {}


def _count_rows(csv_file: Path) -> int | float:
    if not csv_file.exists() or csv_file.stat().st_size == 0:
        return np.nan
    try:
        return len(pd.read_csv(csv_file))
    except Exception:
        return np.nan


def _normalize_cell(v: str) -> str:
    """Normalize a CSV cell value for comparison.

    Floating-point literals may differ in textual precision across engines
    (e.g. "7289.24" vs "7289.2399999999997817"). Parse and re-format with
    6 significant figures so numerically equal values compare equal.
    """
    try:
        f = float(v)
        return f"{f:.6g}"
    except (ValueError, TypeError):
        return v


def _mismatch(results_csv: Path, ref_csv: Path) -> bool | None:
    """True=mismatch, False=match, None=cannot determine (missing reference).

    Compares row counts first (fast), then sorts and compares values if equal counts.
    Header-only reference (0 data rows) matches an empty engine results.csv.
    Columns missing from the engine results count as a mismatch (not None).
    Floating-point values are compared after normalization to 6 significant figures.
    """
    if not ref_csv.exists():
        return None
    try:
        ref_df = pd.read_csv(ref_csv) if ref_csv.stat().st_size > 0 else pd.DataFrame()
        if not results_csv.exists() or results_csv.stat().st_size == 0:
            eng_df = pd.DataFrame()
        else:
            eng_df = pd.read_csv(results_csv)
        if len(ref_df) != len(eng_df):
            return True
        if len(ref_df) == 0:
            return False
        cols = sorted(ref_df.columns)
        if not all(c in eng_df.columns for c in cols):
            return True
        ref_s = ref_df[cols].astype(str).sort_values(by=cols).reset_index(drop=True)
        eng_s = eng_df[cols].astype(str).sort_values(by=cols).reset_index(drop=True)
        ref_n = ref_s.apply(lambda col: col.map(_normalize_cell))
        eng_n = eng_s.apply(lambda col: col.map(_normalize_cell))
        return not ref_n.equals(eng_n)
    except Exception:
        return None


_CORRECTNESS_NAN: dict = {
    "precision": np.nan,
    "recall": np.nan,
    "f1": np.nan,
    "nb_spurious": np.nan,
    "nb_missing": np.nan,
    "nb_duplicates": np.nan,
    "missing_vars": np.nan,
}


def _compare_results(results_csv: Path, ref_csv: Path) -> dict:
    """Row-level correctness metrics between engine output and reference.

    Returns precision, recall, f1, nb_spurious, nb_missing, nb_duplicates,
    missing_vars. All values are np.nan when the reference is absent or an
    exception occurs.
    """
    if not ref_csv.exists():
        return dict(_CORRECTNESS_NAN)
    try:
        ref_df = pd.read_csv(ref_csv) if ref_csv.stat().st_size > 0 else pd.DataFrame()
        if not results_csv.exists() or results_csv.stat().st_size == 0:
            eng_df = pd.DataFrame()
        else:
            eng_df = pd.read_csv(results_csv)

        ref_cols = set(ref_df.columns) if not ref_df.empty else set()
        eng_cols = set(eng_df.columns) if not eng_df.empty else set()
        missing_vars = int(len(ref_cols - eng_cols))

        nb_duplicates = int(len(eng_df) - len(eng_df.drop_duplicates())) if not eng_df.empty else 0

        nb_eng = len(eng_df)
        nb_ref = len(ref_df)

        cols = sorted(ref_df.columns) if not ref_df.empty else []
        shared_cols = [c for c in cols if c in eng_cols]

        if not cols or len(shared_cols) < len(cols):
            intersection = 0
        else:
            ref_norm = ref_df[cols].astype(str).apply(lambda col: col.map(_normalize_cell))
            eng_norm = eng_df[cols].astype(str).apply(lambda col: col.map(_normalize_cell))
            ref_counts: Counter = Counter(map(tuple, ref_norm.itertuples(index=False, name=None)))
            eng_counts: Counter = Counter(map(tuple, eng_norm.itertuples(index=False, name=None)))
            intersection = sum((ref_counts & eng_counts).values())

        nb_spurious = nb_eng - intersection
        nb_missing = nb_ref - intersection

        precision = intersection / nb_eng if nb_eng > 0 else (1.0 if nb_ref == 0 else np.nan)
        recall = intersection / nb_ref if nb_ref > 0 else (1.0 if nb_eng == 0 else np.nan)
        p_r_sum = (precision if not np.isnan(precision) else 0) + (recall if not np.isnan(recall) else 0)
        f1: float
        if np.isnan(precision) and np.isnan(recall):
            f1 = np.nan
        elif p_r_sum == 0:
            f1 = 0.0
        else:
            f1 = 2 * (precision if not np.isnan(precision) else 0) * (recall if not np.isnan(recall) else 0) / p_r_sum

        return {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "nb_spurious": nb_spurious,
            "nb_missing": nb_missing,
            "nb_duplicates": nb_duplicates,
            "missing_vars": missing_vars,
        }
    except Exception:
        return dict(_CORRECTNESS_NAN)


def compute_full_metrics(
    config: BenchmarkConfig,
    bench_dir: "Path | str",
    output_path: "str | Path",
) -> "pd.DataFrame":
    """Comprehensive metrics from stats.csv + provenance.csv + reference results.

    One row per (engine, query, instance, batch, attempt) covering all five
    dimensions: Correção, Tempo, Rede, Seleção, Robustez.
    """
    bench_dir = Path(bench_dir)
    vendor_edges, ratingsite_edges = _vendor_ratingsite_edges(config)
    records = []

    for sf in sorted(bench_dir.glob("evaluation/*/*/*/*/*/stats.csv")):
        meta = _parse_stats_path(str(sf))
        if meta is None:
            continue
        base = sf.parent
        batch = meta["batch"]
        total_sources = int(vendor_edges[batch]) + int(ratingsite_edges[batch])

        stats = _read_stats_row(sf)
        exec_raw = stats.get("exec_time")
        try:
            exec_time = float(exec_raw)
            status = "ok"
        except (TypeError, ValueError):
            exec_time = np.nan
            status = str(exec_raw) if exec_raw is not None else "missing"

        def _f(key: str) -> float:
            try:
                return float(stats.get(key, np.nan))
            except (TypeError, ValueError):
                return np.nan

        results_csv = base / "results.csv"
        ref_csv = (
            bench_dir / "generation" / meta["query"]
            / f"instance_{meta['instance']}" / f"results-batch{batch}.csv"
        )
        nb_res = _count_rows(results_csv) if status == "ok" else np.nan
        nb_ref = _count_rows(ref_csv)
        mm = _mismatch(results_csv, ref_csv) if status == "ok" else None
        correctness = _compare_results(results_csv, ref_csv) if status == "ok" else dict(_CORRECTNESS_NAN)

        tpwss = nb_distinct = rel_sel = np.nan
        avg_rwss = min_rwss = max_rwss = np.nan
        false_positive_sources = redundant_requests = np.nan
        prov = base / "provenance.csv"
        ss_file = base / "source_selection.txt"
        if status == "ok" and prov.exists() and prov.stat().st_size > 0:
            try:
                prov_df = pd.read_csv(prov)
                if not prov_df.empty:
                    nb_distinct = _get_distinct_sources(prov_df)
                    rel_sel = nb_distinct / total_sources
                    tpwss = _get_tpwss(prov_df)
                    avg_rwss = _get_rwss(prov_df, "mean")
                    min_rwss = _get_rwss(prov_df, "min")
                    max_rwss = _get_rwss(prov_df, "max")
                    false_positive_sources = _get_false_positive_sources(ss_file, prov_df)
                    redundant_requests = _get_redundant_requests(ss_file, prov_df)
            except Exception:
                pass

        records.append({
            "engine": meta["engine"],
            "query": meta["query"],
            "instance": meta["instance"],
            "batch": batch,
            "attempt": meta["attempt"],
            "status": status,
            "nb_results": nb_res,
            "nb_ref_results": nb_ref,
            "mismatch": mm,
            "precision": correctness["precision"],
            "recall": correctness["recall"],
            "f1": correctness["f1"],
            "nb_spurious": correctness["nb_spurious"],
            "nb_missing": correctness["nb_missing"],
            "nb_duplicates": correctness["nb_duplicates"],
            "missing_vars": correctness["missing_vars"],
            "exec_time": exec_time,
            "source_selection_time": _f("source_selection_time"),
            "planning_time": _f("planning_time"),
            "join_time": _f("join_time"),
            "ask": _f("ask"),
            "http_req": _f("http_req"),
            "data_transfer": _f("data_transfer"),
            "tpwss": tpwss,
            "avg_rwss": avg_rwss,
            "min_rwss": min_rwss,
            "max_rwss": max_rwss,
            "nb_distinct_sources": nb_distinct,
            "relevant_sources_selectivity": rel_sel,
            "false_positive_sources": false_positive_sources,
            "redundant_requests": redundant_requests,
            "is_timeout": status == "timeout",
            "is_error": status == "error_runtime",
        })

    df = pd.DataFrame.from_records(records)
    df.to_csv(str(output_path), index=False)
    return df


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
            record["status"] = _attempt_status(Path(pf_str).parent / "stats.csv")

        with open(pf_str) as ss_fs:
            content = ss_fs.read().strip()

        failed_attempt = (
            is_evaluation_mode
            and record["status"] not in {"ok", "missing_stats"}
        )
        if not content or failed_attempt:
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
                "avg_rwss": _get_rwss(ss_df, "mean"),
                "min_rwss": _get_rwss(ss_df, "min"),
                "max_rwss": _get_rwss(ss_df, "max"),
            })

        records.append(record)

    metrics_df = pd.DataFrame.from_records(records)
    metrics_df.to_csv(str(output_path), index=False)
    return metrics_df
