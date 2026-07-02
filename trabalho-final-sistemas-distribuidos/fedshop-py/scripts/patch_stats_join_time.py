#!/usr/bin/env python3
"""Retroactively patch existing stats.csv files with join_time and correct FedX unit conversion.

- fedshop-go: reads execution_seconds from sibling fedshop_go_stats.json
- pyfedx:     reads total_seconds - source_selection_seconds from sibling pyfedx_stats.json
- fedx:       reads .txt files, converts source_selection_time/planning_time from ms→s,
              computes join_time = exec_time - ss_time - plan_time

Run from fedshop-py/: uv run python scripts/patch_stats_join_time.py <bench_dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


def patch_fedshop_go(stats_path: Path) -> bool:
    json_path = stats_path.parent / "fedshop_go_stats.json"
    if not json_path.exists():
        return False
    try:
        j = json.loads(json_path.read_text())
    except Exception:
        return False
    exec_s = j.get("execution_seconds")
    if exec_s is None:
        return False

    df = pd.read_csv(stats_path)
    if "join_time" in df.columns and df["join_time"].notna().all():
        return False
    # Only set join_time when exec_time is a valid number (i.e. not "timeout"/"error_runtime")
    def _join(row):
        try:
            float(row["exec_time"])
            return float(exec_s)
        except (TypeError, ValueError):
            return row["exec_time"]  # propagate failure marker

    df["join_time"] = df.apply(_join, axis=1)
    df.to_csv(stats_path, index=False)
    return True


def patch_pyfedx(stats_path: Path) -> bool:
    json_path = stats_path.parent / "pyfedx_stats.json"
    if not json_path.exists():
        return False
    try:
        j = json.loads(json_path.read_text())
    except Exception:
        return False

    total = j.get("total_seconds")
    ss = j.get("source_selection_seconds", 0.0) or 0.0
    plan = j.get("planning_seconds", 0.0) or 0.0
    exec_s = j.get("execution_seconds")  # not present in pyfedx JSON

    if total is None:
        return False

    join_s = float(exec_s) if exec_s is not None else max(0.0, float(total) - float(ss) - float(plan))

    df = pd.read_csv(stats_path)
    if "join_time" in df.columns and df["join_time"].notna().all():
        return False

    def _join(row):
        try:
            float(row["exec_time"])
            return join_s
        except (TypeError, ValueError):
            return row["exec_time"]

    df["join_time"] = df.apply(_join, axis=1)
    df.to_csv(stats_path, index=False)
    return True


def patch_fedx(stats_path: Path) -> bool:
    base = stats_path.parent
    ss_txt = base / "source_selection_time.txt"
    plan_txt = base / "planning_time.txt"
    exec_txt = base / "exec_time.txt"

    df = pd.read_csv(stats_path)
    changed = False

    # Fix unit: source_selection_time and planning_time stored in ms, should be seconds
    for col, txt in (("source_selection_time", ss_txt), ("planning_time", plan_txt)):
        if txt.exists():
            try:
                val_ms = float(txt.read_text())
                val_s = val_ms / 1000.0
                # Only update if current value looks like ms (>= 1.0 and txt exists)
                cur = pd.to_numeric(df[col].iloc[0], errors="coerce") if col in df.columns else None
                if cur is None or (cur >= 1.0 and abs(cur - val_ms) < 1e-3):
                    df[col] = val_s
                    changed = True
            except Exception:
                pass

    # Add join_time
    if "join_time" not in df.columns or df["join_time"].isna().all():
        try:
            exec_t = float(exec_txt.read_text()) if exec_txt.exists() else None
            ss_t = float(ss_txt.read_text()) / 1000.0 if ss_txt.exists() else 0.0
            plan_t = float(plan_txt.read_text()) / 1000.0 if plan_txt.exists() else 0.0
            if exec_t is not None:
                join_t = max(0.0, exec_t - ss_t - plan_t)

                def _join(row):
                    try:
                        float(row["exec_time"])
                        return join_t
                    except (TypeError, ValueError):
                        return row["exec_time"]

                df["join_time"] = df.apply(_join, axis=1)
                changed = True
        except Exception:
            pass

    if changed:
        df.to_csv(stats_path, index=False)
    return changed


PATCHERS = {
    "fedshop-go": patch_fedshop_go,
    "pyfedx": patch_pyfedx,
    "fedx": patch_fedx,
}


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <bench_dir>", file=sys.stderr)
        return 1

    bench_dir = Path(sys.argv[1])
    stats_files = sorted(bench_dir.glob("evaluation/*/*/*/*/*/stats.csv"))
    if not stats_files:
        print(f"No stats.csv found under {bench_dir}/evaluation/", file=sys.stderr)
        return 1

    patched = 0
    for sf in stats_files:
        engine = sf.parts[-6]
        fn = PATCHERS.get(engine)
        if fn is None:
            continue
        if fn(sf):
            print(f"  patched {sf.relative_to(bench_dir)}")
            patched += 1

    print(f"\nDone: {patched} stats.csv files updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
