#!/usr/bin/env python3
"""Retroactively patch RSA attempt_0 stats.csv with timing breakdowns from attempt_2.

For each RSA (query, instance, batch):
  - Read source_selection_time and planning_time from attempt_2 (FedUP always runs)
  - If attempt_2 was ok: set join_time from attempt_2's join_time
  - If attempt_2 timed out (q02, q04): estimate join_time = exec_time_a0 - fedup_time_a2
  - Write these metrics into attempt_0/stats.csv

Run from fedshop-py/: uv run python scripts/patch_rsa_timing.py <bench_dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <bench_dir>", file=sys.stderr)
        return 1

    bench_dir = Path(sys.argv[1])
    rsa_dir = bench_dir / "evaluation" / "rsa"
    if not rsa_dir.exists():
        print(f"RSA eval dir not found: {rsa_dir}", file=sys.stderr)
        return 1

    patched = 0
    for q_dir in sorted(rsa_dir.iterdir()):
        for inst_dir in sorted(q_dir.iterdir()):
            for batch_dir in sorted(inst_dir.iterdir()):
                a0 = batch_dir / "attempt_0" / "stats.csv"
                if not a0.exists():
                    continue

                df0 = pd.read_csv(a0)
                exec_time_a0 = pd.to_numeric(df0["exec_time"].iloc[0], errors="coerce")
                if pd.isna(exec_time_a0):
                    continue  # attempt_0 failed, nothing to patch

                fedup_seconds = None
                join_seconds = None

                # Try each timing attempt (best timing data wins)
                for attempt_n in ("attempt_2", "attempt_4", "attempt_1"):
                    a_csv = batch_dir / attempt_n / "stats.csv"
                    if not a_csv.exists():
                        continue
                    df_a = pd.read_csv(a_csv)
                    ss_a = pd.to_numeric(df_a.get("source_selection_time", pd.Series([None])).iloc[0], errors="coerce")
                    if pd.isna(ss_a):
                        continue  # this attempt also failed to capture FedUP time
                    jt_a = pd.to_numeric(df_a.get("join_time", pd.Series([None])).iloc[0], errors="coerce")
                    exec_a = pd.to_numeric(df_a["exec_time"].iloc[0], errors="coerce")

                    fedup_seconds = float(ss_a)
                    if not pd.isna(jt_a):
                        join_seconds = float(jt_a)
                    elif not pd.isna(exec_a):
                        join_seconds = max(0.0, float(exec_a) - fedup_seconds)
                    else:
                        # ARQ failed/timed out: estimate join from attempt_0 exec_time
                        join_seconds = max(0.0, exec_time_a0 - fedup_seconds)
                    break  # use first attempt that has valid FedUP timing

                # Fall back to txt files
                if fedup_seconds is None:
                    for attempt_n in ("attempt_2", "attempt_4"):
                        ss_txt = batch_dir / attempt_n / "source_selection_time.txt"
                        jt_txt = batch_dir / attempt_n / "join_time.txt"
                        if ss_txt.exists():
                            try:
                                fedup_seconds = float(ss_txt.read_text())
                                if jt_txt.exists():
                                    join_seconds = float(jt_txt.read_text())
                                if join_seconds is None:
                                    join_seconds = max(0.0, exec_time_a0 - fedup_seconds)
                                break
                            except ValueError:
                                pass

                if fedup_seconds is None:
                    print(f"  skip {a0} — no timing data in any attempt")
                    continue

                # Already patched?
                if ("source_selection_time" in df0.columns and
                        not pd.isna(pd.to_numeric(df0["source_selection_time"].iloc[0], errors="coerce"))):
                    print(f"  already patched {a0.relative_to(bench_dir)}")
                    continue

                df0["source_selection_time"] = fedup_seconds
                df0["planning_time"] = fedup_seconds
                if join_seconds is not None:
                    df0["join_time"] = join_seconds

                df0.to_csv(a0, index=False)
                tag = "(exact)" if join_seconds is not None else "(fedup only)"
                print(f"  patched {a0.relative_to(bench_dir)} ss={fedup_seconds:.3f}s jt={join_seconds:.3f}s {tag}")
                patched += 1

    print(f"\nDone: {patched} RSA attempt_0 stats.csv files patched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
